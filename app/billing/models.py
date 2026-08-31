import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan"
    __table_args__ = {"comment": "Offre commerciale pour un module donné (prix, période, fonctionnalités incluses)."}

    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    priceCents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XAF")
    periodDays: Mapped[int] = mapped_column(nullable=False, default=30)


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscription"
    __table_args__ = {"comment": "Abonnement d'une organisation à un plan — statut trial/active/expired/cancelled."}

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    planId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="trial")
    startDate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endDate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoice"
    __table_args__ = {"comment": "Facture émise pour un abonnement — le règlement réel (prestataire de paiement) n'est pas implémenté dans ce socle."}

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True
    )
    amountCents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XAF")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending | paid | failed
    issuedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paidAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
