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
    """

    __tablename__ = "outbox_evenement"
    __table_args__ = (
        CheckConstraint("statut IN ('publie')", name="ck_outbox_evenement_statut"),
        {"comment": "Outbox : événements de domaine écrits dans la transaction métier, publiés après commit."},
    )

    eventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    eventType: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    schemaVersion: Mapped[int] = mapped_column(Integer, nullable=False)
    tenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Classification de la donnée, reprise de l'enveloppe (BE-174). Nullable : les lignes
    # antérieures à la migration 174a0b1c2d3e n'ont pas de classification connue.
    dataClassification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, server_default="publie")
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
