import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint
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
    planVersionId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("planVersion.id"), nullable=True, index=True)
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
    amountMinor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotencyKey: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)


class PlanVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable published price/entitlement snapshot for a catalog plan."""
    __tablename__ = "planVersion"
    __table_args__ = (UniqueConstraint("planId", "version", name="uq_planVersion_plan_version"),)

    planId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    amountMinor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    periodDays: Mapped[int] = mapped_column(nullable=False)
    entitlementCodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    effectiveAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SubscriptionEntitlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptionEntitlement"
    __table_args__ = (UniqueConstraint("subscriptionId", "entitlementCode", name="uq_subscriptionEntitlement_subscription_code"),)

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True)
    subscriptionId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True)
    moduleCode: Mapped[str] = mapped_column(String(100), nullable=False)
    entitlementCode: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    startsAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endsAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paymentAttempt"
    __table_args__ = (
        UniqueConstraint("idempotencyKey", name="uq_paymentAttempt_idempotency"),
        UniqueConstraint("provider", "providerReference", name="uq_paymentAttempt_provider_reference"),
    )

    invoiceId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    idempotencyKey: Mapped[str] = mapped_column(String(120), nullable=False)
    providerReference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    amountMinor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    checkoutUrl: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    requestedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaymentWebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paymentWebhookEvent"
    __table_args__ = (UniqueConstraint("provider", "eventId", name="uq_paymentWebhookEvent_provider_event"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    eventId: Mapped[str] = mapped_column(String(160), nullable=False)
    eventType: Mapped[str] = mapped_column(String(100), nullable=False)
    payloadDigest: Mapped[str] = mapped_column(String(64), nullable=False)
    signatureVerified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requestId: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="received")
