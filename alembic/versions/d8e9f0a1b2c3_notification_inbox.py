"""Add recipient-scoped in-app notification inbox.

Revision ID: d8e9f0a1b2c3
Revises: c0b7d9a2e511
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c0b7d9a2e511"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notificationInboxItem",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipientUserId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sourceEventType", sa.String(length=80), nullable=False),
        sa.Column("sourceEventId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("readAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipientUserId"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organizationId", "recipientUserId", "sourceEventType", "sourceEventId",
            name="uq_notificationInboxItem_event_recipient",
        ),
        comment="Notification in-app explicitement adressée; aucun canal ni rétention automatisée implicite.",
    )
    op.create_index(
        "ix_notificationInboxItem_recipient_created",
        "notificationInboxItem",
        ["organizationId", "recipientUserId", "createdAt"],
    )
    op.create_index(
        "ix_notificationInboxItem_recipient_read",
        "notificationInboxItem",
        ["organizationId", "recipientUserId", "readAt"],
    )


def downgrade() -> None:
    op.drop_index("ix_notificationInboxItem_recipient_read", table_name="notificationInboxItem")
    op.drop_index("ix_notificationInboxItem_recipient_created", table_name="notificationInboxItem")
    op.drop_table("notificationInboxItem")
