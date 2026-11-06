"""Add payment_method_reference table for payment method tokens (BE-116).

Revision ID: c9d8e7f6a5b4
Revises: b108c4a1d2e3
Create Date: 2026-11-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, None] = "b108c4a1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_method_reference",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organizationId", sa.UUID(), nullable=False),
        sa.Column("tokenReference", sa.String(length=255), nullable=False),
        sa.Column("selected", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Références de token des moyens de paiement par organisation, sans donnée de carte (BE-116).",
    )
    op.create_index(op.f("ix_payment_method_reference_organizationId"), "payment_method_reference", ["organizationId"], unique=False)
    op.create_index(
        "uq_payment_method_reference_selection",
        "payment_method_reference",
        ["organizationId"],
        unique=True,
        postgresql_where=sa.text("selected"),
    )


def downgrade() -> None:
    op.drop_index("uq_payment_method_reference_selection", table_name="payment_method_reference")
    op.drop_index(op.f("ix_payment_method_reference_organizationId"), table_name="payment_method_reference")
    op.drop_table("payment_method_reference")
