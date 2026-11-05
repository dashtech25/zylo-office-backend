"""Journal d'audit métier : table unique `audit_event` (BE-007).

Décision D2 : une seule table d'audit. L'ancienne table `auditLog` est renommée
en `audit_event` par la migration de BE-007 ; aucune autre table d'audit ne doit
être créée. Les lignes reprises gardent leurs colonnes, reçoivent un `eventId`
égal à leur identifiant, un `request_id` égal à leur identifiant (la requête
d'origine n'était pas tracée) et `result = 'success'`.

Écriture : uniquement via `app.audit.service.record_audit_event`, dans la
transaction de l'action journalisée. Lecture : `app.audit.service.list_audit_logs`
(BE-033 consommera la même table).

Valeurs de référence :
- `result` : `success` | `refused` | `error` (CHECK en base) ;
- `actorType` : `humain` | `service` | `systeme` (CHECK en base) ;
- `organizationId` est nul uniquement pour une portée plateforme, à venir ; le
  service refuse aujourd'hui toute écriture sans organisation (BE-007 CA-3).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Une entrée du journal d'audit : qui a fait quoi, sur quel élément, quand,
    avec quel résultat, et sous quel request ID.

    Le texte `summary` est pré-rendu au moment de l'écriture (§15.2) pour rester
    lisible si le libellé d'une action évolue plus tard. `changes` ne contient
    jamais de secret : le service retire les clés sensibles avant l'écriture."""

    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint("result IN ('success', 'refused', 'error')", name="ck_audit_event_result"),
        CheckConstraint("\"actorType\" IN ('humain', 'service', 'systeme')", name="ck_audit_event_actorType"),
        # BE-152 CA-3 : une action, une cible (entityType) ou une corrélation (request_id)
        # vide ou faite d'espaces est refusée par la base. NOT NULL ne suffit pas pour
        # une chaîne vide ; l'acteur (actorUserId) reste NOT NULL.
        CheckConstraint("length(btrim(action)) > 0", name="ck_audit_event_action_non_vide"),
        CheckConstraint('length(btrim("entityType")) > 0', name="ck_audit_event_entityType_non_vide"),
        CheckConstraint('length(btrim("request_id")) > 0', name="ck_audit_event_request_id_non_vide"),
        Index("ix_audit_event_organizationId_createdAt", "organizationId", "createdAt"),
        {"comment": "Journal d'audit métier unique : qui a fait quoi, sur quel élément, quand, avec quel résultat."},
    )

    # Nullable depuis BE-007 pour la portée plateforme ; le service exige encore
    # une organisation (CA-3).
    organizationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    actorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)

    action: Mapped[str] = mapped_column(String(150), nullable=False, index=True)  # ex: "zyloLiquid.price.update"
    entityType: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "FuelProduct"
    entityId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Dénormalisé depuis l'entité concernée pour permettre le filtrage par
    # portée sans jointure (§17 : même mécanisme de scope que les grants).
    scopeResourceType: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    scopeResourceId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Texte pré-rendu côté serveur au moment de l'écriture (§15.2) — jamais
    # reconstruit à l'affichage à partir du seul code d'action, pour rester
    # lisible même si le wording évolue plus tard sans réécrire l'historique.
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    ipAddress: Mapped[str | None] = mapped_column(String(64), nullable=True)
    userAgent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Colonnes ajoutées par BE-007 (QE-SOC-22 et demandes de BE-122, BE-152, BE-227).
    # request_id : identifiant de corrélation de la requête (en-tête X-Request-Id).
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # result : issue de l'action (succès, refus de droits ou de règle, erreur).
    result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="success")
    # eventId : identifiant métier unique d'une entrée (distinct de la clé primaire).
    eventId: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    actorType: Mapped[str] = mapped_column(String(16), nullable=False, server_default="humain")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approvalId: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schemaVersion: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Valeurs de visibilité et de classification : NON DÉFINI (à trancher avec BE-033).
    visibility: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dataClassification: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Colonnes ajoutées par BE-056 (événements de transition de module, voir
    # app/modules_registry/evenements.py). Toutes nulles pour les entrées d'audit métier existantes.
    # subjectType / subjectId : sujet de la transition (ex. `tenant_module`, identifiant d'installation).
    subjectType: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subjectId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # eventName : nom de l'événement publié (ex. `ModuleSuspended`), nul pour une entrée d'audit métier.
    eventName: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # origin : origine de la transition (client, commercial, security, support, automation, platform).
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # correlationId : identifiant de corrélation (X-Request-Id, sinon identifiant d'opération).
    correlationId: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # payloadMinimal : charge utile minimale, sans secret ni contenu métier (contrôlée à l'écriture).
    payloadMinimal: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# Alias de compatibilité : les modules existants importent encore `AuditLog`.
# Il pointe vers la même table `audit_event`. À retirer quand tous les imports
# auront été renommés (hors périmètre de BE-007).
AuditLog = AuditEvent
