"""Table des intentions de commande opérateur (BE-124).

Revision ID: c124a0de0124
Revises: 3a2990daf8ef
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c124a0de0124"
down_revision: Union[str, None] = "3a2990daf8ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_command",
        sa.Column("commandId", sa.UUID(), nullable=False),
        sa.Column("commandType", sa.String(length=80), nullable=False),
        sa.Column("commandVersion", sa.Integer(), server_default="1", nullable=False),
        sa.Column("actorId", sa.UUID(), nullable=False),
        sa.Column("approverId", sa.UUID(), nullable=True),
        sa.Column("effectiveRole", sa.String(length=64), nullable=False),
        sa.Column("effectiveScope", sa.String(length=80), nullable=False),
        sa.Column("tenantId", sa.UUID(), nullable=True),
        sa.Column("targetObjectType", sa.String(length=60), nullable=False),
        sa.Column("targetObjectId", sa.String(length=120), nullable=False),
        sa.Column("targetVersionExpected", sa.Integer(), nullable=True),
        sa.Column("reasonTicket", sa.String(length=120), nullable=False),
        sa.Column("idempotencyKey", sa.String(length=120), nullable=False),
        sa.Column("correlationId", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="intention", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("createdAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiresAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('intention')", name="ck_admin_command_status"),
        sa.CheckConstraint("\"commandVersion\" >= 1", name="ck_admin_command_version"),
        sa.ForeignKeyConstraint(["actorId"], ["user.id"]),
        sa.ForeignKeyConstraint(["approverId"], ["user.id"]),
        sa.ForeignKeyConstraint(["tenantId"], ["organization.id"]),
        sa.PrimaryKeyConstraint("commandId"),
        sa.UniqueConstraint("actorId", "idempotencyKey", name="uq_admin_command_actor_idempotency"),
        comment="Intentions de commande opérateur, idempotentes par acteur (BE-124).",
    )
    op.create_index("ix_admin_command_actorId", "admin_command", ["actorId"])
    op.create_index("ix_admin_command_tenantId", "admin_command", ["tenantId"])


def downgrade() -> None:
    op.drop_index("ix_admin_command_tenantId", table_name="admin_command")
    op.drop_index("ix_admin_command_actorId", table_name="admin_command")
    op.drop_table("admin_command")
