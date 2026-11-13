"""Table des clés d'idempotence des commandes (BE-232).

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f123
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b7c8d9e0f123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotencyKeys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organizationId", sa.UUID(), nullable=False),
        sa.Column("actorId", sa.UUID(), nullable=False),
        sa.Column("idempotencyKey", sa.String(length=120), nullable=False),
        sa.Column("requestHash", sa.String(length=64), nullable=False),
        sa.Column("responseStatus", sa.Integer(), nullable=True),
        sa.Column("responseBody", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organizationId", "actorId", "idempotencyKey", name="uq_idempotencyKey_scope"),
        comment="Clés d'idempotence des commandes mutantes : une réponse mémorisée par (organisation, acteur, clé).",
    )
    op.create_index("ix_idempotencyKey_expiresAt", "idempotencyKeys", ["expiresAt"])


def downgrade() -> None:
    op.drop_index("ix_idempotencyKey_expiresAt", table_name="idempotencyKeys")
    op.drop_table("idempotencyKeys")
