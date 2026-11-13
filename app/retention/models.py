"""Modèles BE-214 : Rétention, sauvegarde et purge.

Contrat (BE-214) :
- `RetentionPolicy` : durées de rétention par catégorie de données.
  Catégories : audit, logs, exports, etc.
  Durée NULL = non défini, aucune purge.
- `LegalHold` : verrous légaux empêchant la purge d'un tenant.
  Scope : tenant ou organisation.
  setAt : date du verrou, releasedAt : date de libération (NULL si actif).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class RetentionPolicy(Base):
    """Politique de rétention par catégorie de données.

    Durée en jours. NULL = non défini, aucune purge automatique.
    """

    __tablename__ = "retention_policy"
    __table_args__ = (
        Index("ix_retention_policy_category", "category"),
        {"comment": "Politique de rétention : catégories et durées (BE-214)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(100), nullable=False, unique=True,
                                         comment="Catégorie : audit, logs, exports, etc.")
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                      comment="Durée de rétention en jours (NULL = non défini, aucune purge).")
    description: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                    comment="Description de la politique.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class LegalHold(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Verrou légal empêchant la purge de données.

    Un legal_hold actif (releasedAt IS NULL) bloque toute purge
    pour le tenant/organisation cible. Immuable après création.
    """

    __tablename__ = "legal_hold"
    __table_args__ = (
        Index("ix_legal_hold_tenant_id", "tenantId"),
        Index("ix_legal_hold_scope", "scope"),
        {"comment": "Verrou légal : bloque la purge jusqu'à libération (BE-214)."},
    )

    tenantId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False,
        comment="Tenant/organisation verrouillée.",
    )
    scope: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Scope du verrou : tenant, organization, etc.",
    )
    setAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Date de mise en place du verrou.",
    )
    releasedAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Date de libération (NULL = actif, en cours).",
    )
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Motif du verrou.",
    )
