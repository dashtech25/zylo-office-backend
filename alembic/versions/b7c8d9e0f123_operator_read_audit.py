"""Add minimal audit records for sensitive operator reads.

Revision ID: b7c8d9e0f123
Revises: e3c4a8f1b2d6
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f123"
down_revision: Union[str, None] = "e3c4a8f1b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operatorAuditLog",
        sa.Column("actorUserId", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("targetType", sa.String(length=80), nullable=False),
        sa.Column("targetId", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("requestId", sa.String(length=128), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["actorUserId"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operatorAuditLog_actorUserId"), "operatorAuditLog", ["actorUserId"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_scope"), "operatorAuditLog", ["scope"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_action"), "operatorAuditLog", ["action"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_requestId"), "operatorAuditLog", ["requestId"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_createdAt"), "operatorAuditLog", ["createdAt"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_operatorAuditLog_createdAt"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_requestId"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_action"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_scope"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_actorUserId"), table_name="operatorAuditLog")
    op.drop_table("operatorAuditLog")
