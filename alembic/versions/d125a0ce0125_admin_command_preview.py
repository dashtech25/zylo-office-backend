"""Table des prévisualisations de commande opérateur (BE-125).

Revision ID: d125a0ce0125
Revises: 5e31981cf46c
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d125a0ce0125"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_command_preview",
        sa.Column("previewId", sa.UUID(), nullable=False),
        sa.Column("commandId", sa.UUID(), nullable=False),
        sa.Column("stateSnapshotHash", sa.String(length=64), nullable=False),
        sa.Column("effects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expiresAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidatedReason", sa.String(length=40), nullable=True),
        sa.Column("confirmedAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["commandId"], ["admin_command.commandId"]),
        sa.PrimaryKeyConstraint("previewId"),
        comment="Prévisualisation d'une commande opérateur, expirable et invalidable (BE-125).",
    )
    op.create_index("ix_admin_command_preview_commandId", "admin_command_preview", ["commandId"])


def downgrade() -> None:
    op.drop_index("ix_admin_command_preview_commandId", table_name="admin_command_preview")
    op.drop_table("admin_command_preview")
