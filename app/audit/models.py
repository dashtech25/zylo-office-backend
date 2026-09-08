import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Journal d'audit centralisé — résout le TODO explicitement laissé
    "à valider" dans `app/modules/zylo_liquid/models.py` (table
    `audit_logs`). Voir « rôle et permissions global global et spécifique
    par module Zylo Office.md » §15 : chaque module appelle explicitement
    `record_audit_event(...)` au point d'exécution d'une action sensible
    (opt-in, comme `tracking=True` chez Odoo) — jamais un hook ORM générique
    qui journaliserait toute écriture indistinctement."""

    __tablename__ = "auditLog"
    __table_args__ = {"comment": "Journal d'audit — qui a fait quoi, sur quel élément, quand."}

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
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
