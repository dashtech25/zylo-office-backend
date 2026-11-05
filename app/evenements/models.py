"""Tables de l'outbox et de la consommation idempotente (BE-166).

Rôle : persister les événements de domaine dans la même transaction que la mutation
métier qui les produit (`outbox_evenement`), et consigner, par consommateur, les
événements déjà traités (`consommation_evenement`) pour qu'une livraison répétée ne
produise qu'un seul effet.

Invariants :
- `outbox_evenement.eventId` est unique : publier deux fois le même événement ne crée
  qu'une ligne (déduplication à l'écriture, voir `app.evenements.outbox`) ;
- `consommation_evenement` est unique par couple (`consommateur`, `eventId`) : c'est
  cette contrainte qui rend la consommation idempotente ;
- le mécanisme de file qui pousse ces lignes vers des consommateurs externes n'est pas
  défini (QE-PAR-10) : aucune table de file ni de worker n'est créée ici.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class OutboxEvenement(UUIDPrimaryKeyMixin, Base):
    """Une ligne de l'outbox : un événement validé, rattaché à son tenant.

    `payload` contient l'enveloppe canonique complète (BE-150), telle que validée. La
    ligne n'est visible aux autres transactions qu'après le commit de la transaction
    métier qui l'a écrite (CA-1).

    BE-234 : `portee` distingue un événement de tenant (`tenantId` renseigné) d'un
    événement plateforme (`tenantId` nul, type dans l'espace `Plateforme.`). La contrainte
    `ck_outbox_evenement_portee` impose cette cohérence en base. `acteur` et `correlationId`
    sont recopiés de l'enveloppe pour être interrogeables sans décoder `payload`. `tentatives`
    est réservé à la consommation (BE-235) : la publication l'initialise à 0 et ne le modifie pas.
    """

    __tablename__ = "outbox_evenement"
    __table_args__ = (
        CheckConstraint("statut IN ('publie')", name="ck_outbox_evenement_statut"),
        CheckConstraint("portee IN ('tenant', 'plateforme')", name="ck_outbox_evenement_portee"),
        CheckConstraint(
            "(portee = 'tenant' AND \"tenantId\" IS NOT NULL) OR (portee = 'plateforme' AND \"tenantId\" IS NULL)",
            name="ck_outbox_evenement_portee_tenant",
        ),
        {"comment": "Outbox : événements de domaine écrits dans la transaction métier, publiés après commit."},
    )

    eventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    eventType: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    schemaVersion: Mapped[int] = mapped_column(Integer, nullable=False)
    portee: Mapped[str] = mapped_column(String(20), nullable=False, server_default="tenant")
    tenantId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True)
    acteur: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    correlationId: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Classification de la donnée, reprise de l'enveloppe (BE-174). Nullable : les lignes
    # antérieures à la migration 174a0b1c2d3e n'ont pas de classification connue.
    dataClassification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, server_default="publie")
    tentatives: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    publieAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConsommationEvenement(UUIDPrimaryKeyMixin, Base):
    """Trace qu'un consommateur a traité un événement.

    L'unicité du couple (`consommateur`, `eventId`) est la garantie de non-double effet
    (CA-2) : la seconde insertion échoue, et l'appelant consigne alors `REPLAY_DUPLICATE`.
    """

    __tablename__ = "consommation_evenement"
    __table_args__ = (
        UniqueConstraint("consommateur", "eventId", name="uq_consommation_evenement_consommateur_event"),
        {"comment": "Consommation idempotente : un consommateur ne traite un événement qu'une fois."},
    )

    consommateur: Mapped[str] = mapped_column(String(150), nullable=False)
    eventId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_evenement.eventId"), nullable=False, index=True
    )
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeadLetter(UUIDPrimaryKeyMixin, Base):
    """Entrée de la file de lettres mortes (BE-235) : un événement dont le consommateur a épuisé ses tentatives.

    Une entrée est créée seulement après le dernier échec d'un consommateur (CA-2). Elle porte
    le tenant pour l'isolation (CA-4) et le nom de la classe d'erreur, jamais le message d'erreur
    ni le payload : le motif ne doit pas exposer de donnée métier dans les journaux ou l'API.

    `statut` vaut `en_attente` jusqu'au replay réussi, puis `rejoue`. L'unicité du couple
    (`consommateur`, `eventId`) empêche deux entrées pour le même échec : un lot relancé ne
    rejoue pas un message déjà en DLQ.
    """

    __tablename__ = "dead_letters"
    __table_args__ = (
        UniqueConstraint("consommateur", "eventId", name="uq_dead_letters_consommateur_event"),
        CheckConstraint("statut IN ('en_attente', 'rejoue')", name="ck_dead_letters_statut"),
        {"comment": "File de lettres mortes : événements en échec définitif pour un consommateur, rejouables par un opérateur."},
    )

    eventId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_evenement.eventId"), nullable=False, index=True
    )
    consommateur: Mapped[str] = mapped_column(String(150), nullable=False)
    motif: Mapped[str] = mapped_column(String(200), nullable=False)
    tentatives: Mapped[int] = mapped_column(Integer, nullable=False)
    tenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, server_default="en_attente")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    rejoueAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
