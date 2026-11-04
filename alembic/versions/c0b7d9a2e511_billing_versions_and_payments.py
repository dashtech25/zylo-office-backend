"""Add immutable price versions, entitlements, payment attempts and webhook idempotency.

Revision ID: c0b7d9a2e511
Revises: d0c526c8656e
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c0b7d9a2e511"
down_revision: Union[str, None] = "d0c526c8656e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "planVersion",
        sa.Column("planId", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("amountMinor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("periodDays", sa.Integer(), nullable=False),
        sa.Column("entitlementCodes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("effectiveAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["planId"], ["plan.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("planId", "version", name="uq_planVersion_plan_version"),
    )
    op.create_index("ix_planVersion_planId", "planVersion", ["planId"])
    op.execute(sa.text('''
        INSERT INTO "planVersion"
            ("id", "planId", "version", "amountMinor", "currency", "periodDays", "entitlementCodes", "status", "effectiveAt", "createdAt", "updatedAt")
        SELECT gen_random_uuid(), id, 1, "priceCents"::bigint, currency, "periodDays", '[]'::json, 'active', now(), now(), now()
        FROM plan
    '''))
    op.add_column("subscription", sa.Column("planVersionId", sa.UUID(), nullable=True))
    op.create_index("ix_subscription_planVersionId", "subscription", ["planVersionId"])
    op.create_foreign_key("fk_subscription_planVersionId_planVersion", "subscription", "planVersion", ["planVersionId"], ["id"])
    op.execute(sa.text('''
        UPDATE subscription s SET "planVersionId" = pv.id
        FROM "planVersion" pv WHERE pv."planId" = s."planId" AND pv.version = 1
    '''))
    op.add_column("invoice", sa.Column("amountMinor", sa.BigInteger(), nullable=True))
    op.add_column("invoice", sa.Column("idempotencyKey", sa.String(120), nullable=True))
    op.create_unique_constraint("uq_invoice_idempotencyKey", "invoice", ["idempotencyKey"])
    # Preserve each legacy integer exactly: `amountCents` is Numeric(12,0),
    # and this migration does no currency-dependent rescaling. Keep NULL only
    # for a legacy NULL, if one exists.
    op.execute(sa.text('''
        UPDATE invoice SET "amountMinor" = "amountCents"::bigint
        WHERE "amountCents" IS NOT NULL
    '''))
    op.create_table(
        "subscriptionEntitlement",
        sa.Column("organizationId", sa.UUID(), nullable=False),
        sa.Column("subscriptionId", sa.UUID(), nullable=False),
        sa.Column("moduleCode", sa.String(100), nullable=False),
        sa.Column("entitlementCode", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("startsAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endsAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.ForeignKeyConstraint(["subscriptionId"], ["subscription.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscriptionId", "entitlementCode", name="uq_subscriptionEntitlement_subscription_code"),
    )
    op.create_index("ix_subscriptionEntitlement_organizationId", "subscriptionEntitlement", ["organizationId"])
    op.create_index("ix_subscriptionEntitlement_subscriptionId", "subscriptionEntitlement", ["subscriptionId"])
    op.create_table(
        "paymentAttempt",
        sa.Column("invoiceId", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("idempotencyKey", sa.String(120), nullable=False),
        sa.Column("providerReference", sa.String(160), nullable=True),
        sa.Column("amountMinor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("checkoutUrl", sa.String(1000), nullable=True),
        sa.Column("requestedAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["invoiceId"], ["invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotencyKey", name="uq_paymentAttempt_idempotency"),
        sa.UniqueConstraint("provider", "providerReference", name="uq_paymentAttempt_provider_reference"),
    )
    op.create_index("ix_paymentAttempt_invoiceId", "paymentAttempt", ["invoiceId"])
    op.create_table(
        "paymentWebhookEvent",
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("eventId", sa.String(160), nullable=False),
        sa.Column("eventType", sa.String(100), nullable=False),
        sa.Column("payloadDigest", sa.String(64), nullable=False),
        sa.Column("signatureVerified", sa.Boolean(), nullable=False),
        sa.Column("requestId", sa.String(128), nullable=True),
        sa.Column("processedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "eventId", name="uq_paymentWebhookEvent_provider_event"),
    )


def downgrade() -> None:
    op.drop_table("paymentWebhookEvent")
    op.drop_index("ix_paymentAttempt_invoiceId", table_name="paymentAttempt")
    op.drop_table("paymentAttempt")
    op.drop_index("ix_subscriptionEntitlement_subscriptionId", table_name="subscriptionEntitlement")
    op.drop_index("ix_subscriptionEntitlement_organizationId", table_name="subscriptionEntitlement")
    op.drop_table("subscriptionEntitlement")
    op.drop_constraint("uq_invoice_idempotencyKey", "invoice", type_="unique")
    op.drop_column("invoice", "idempotencyKey")
    op.drop_column("invoice", "amountMinor")
    op.drop_constraint("fk_subscription_planVersionId_planVersion", "subscription", type_="foreignkey")
    op.drop_index("ix_subscription_planVersionId", table_name="subscription")
    op.drop_column("subscription", "planVersionId")
    op.drop_index("ix_planVersion_planId", table_name="planVersion")
    op.drop_table("planVersion")
