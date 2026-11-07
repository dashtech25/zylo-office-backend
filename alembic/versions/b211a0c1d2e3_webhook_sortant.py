"""webhook sortant : endpoints et livraisons (BE-211)

Revision ID: b211a0c1d2e3
Revises: 2402c108f2e6
Create Date: 2026-11-07 15:00:00.000000

Tables `webhook_endpoint` (destination, référence de secret sans valeur, fenêtre de rotation)
et `webhook_delivery` (une livraison par couple endpoint et événement, tentatives, statut,
prochaine tentative). Contraintes : état et statut bornés par CHECK, unicité (endpoint,
événement).
Downgrade : suppression des deux tables, dans l'ordre inverse de création.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b211a0c1d2e3"
down_revision: Union[str, None] = "2402c108f2e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoint",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secretRef", sa.String(length=255), nullable=False),
        sa.Column("secretPrecedentRef", sa.String(length=255), nullable=True),
        sa.Column("overlapJusquA", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('active', 'revoked')", name="ck_webhook_endpoint_state"),
        sa.CheckConstraint("length(btrim(url)) > 0", name="ck_webhook_endpoint_url_non_vide"),
        comment="Endpoints de webhook sortant par tenant, référence de secret sans valeur (BE-211).",
    )
    op.create_index("ix_webhook_endpoint_organizationId", "webhook_endpoint", ["organizationId"])

    op.create_table(
        "webhook_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpointId", postgresql.UUID(as_uuid=True), sa.ForeignKey("webhook_endpoint.id"), nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("eventId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("nextAttemptAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'failed', 'delivered', 'dlq')", name="ck_webhook_delivery_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_webhook_delivery_attempts_positive"),
        sa.UniqueConstraint("endpointId", "eventId", name="uq_webhook_delivery_endpoint_event"),
        comment="Livraisons de webhook sortant, tentatives et DLQ par endpoint (BE-211).",
    )
    op.create_index("ix_webhook_delivery_endpointId", "webhook_delivery", ["endpointId"])
    op.create_index("ix_webhook_delivery_organizationId", "webhook_delivery", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_webhook_delivery_organizationId", table_name="webhook_delivery")
    op.drop_index("ix_webhook_delivery_endpointId", table_name="webhook_delivery")
    op.drop_table("webhook_delivery")
    op.drop_index("ix_webhook_endpoint_organizationId", table_name="webhook_endpoint")
    op.drop_table("webhook_endpoint")
