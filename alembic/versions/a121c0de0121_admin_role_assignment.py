"""Table des affectations de rôle d'administration globales et temporaires (BE-121).

Revision ID: a121c0de0121
Revises: 254220e168b5
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a121c0de0121"
down_revision: Union[str, None] = "254220e168b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_role_assignment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actorId", sa.UUID(), nullable=False),
        sa.Column("roleCode", sa.String(length=60), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("grantedBy", sa.UUID(), nullable=False),
        sa.Column("grantedAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actorId"], ["user.id"]),
        sa.ForeignKeyConstraint(["grantedBy"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Affectation de rôle d'administration globale ou temporaire (BE-121).",
    )
    op.create_index("ix_admin_role_assignment_actorId", "admin_role_assignment", ["actorId"])


def downgrade() -> None:
    op.drop_index("ix_admin_role_assignment_actorId", table_name="admin_role_assignment")
    op.drop_table("admin_role_assignment")
