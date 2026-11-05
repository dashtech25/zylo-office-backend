"""Table des notifications liées aux commandes opérateur (BE-144).

Revision ID: e144a0de0144
Revises: f32497e0328e
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e144a0de0144"
down_revision: Union[str, None] = "f32497e0328e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_notification",
        sa.Column("notificationId", sa.UUID(), nullable=False),
        sa.Column("commandId", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=True),
        sa.Column("recipientRef", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sentAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failureReason", sa.String(length=80), nullable=True),
        sa.Column("createdAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('envoyee', 'echec')", name="ck_admin_notification_status"),
        sa.ForeignKeyConstraint(["commandId"], ["admin_command.commandId"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("notificationId"),
        comment="Notifications liées aux commandes opérateur, sans charge utile brute (BE-144).",
    )
    op.create_index("ix_admin_notification_commandId", "admin_notification", ["commandId"])


def downgrade() -> None:
    op.drop_index("ix_admin_notification_commandId", table_name="admin_notification")
    op.drop_table("admin_notification")
