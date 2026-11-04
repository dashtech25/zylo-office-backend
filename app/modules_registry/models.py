import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Module(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "module"
    __table_args__ = {"comment": "Registre statique des modules connus du système (CRM, Stock, zylo_liquid...)."}

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.1.0")
    # Version du contrat de manifeste (format non défini, QE-SOC-19). Hors de
    # VERSIONS_MANIFESTE_SUPPORTEES, le module passe à l'état `incompatible` (etats.py).
    manifestVersion: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="Version du contrat de manifeste du module."
    )


class OrganizationModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizationModule"
    __table_args__ = (
        UniqueConstraint("organizationId", "moduleCode", name="uq_organizationModule_org_module"),
        {"comment": "État d'activation d'un module pour une organisation donnée (active/inactive/trial)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="inactive")  # active | inactive | trial
    activatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
