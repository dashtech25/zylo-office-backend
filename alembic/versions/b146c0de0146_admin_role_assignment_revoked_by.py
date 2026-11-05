"""Colonne `revokedBy` sur `admin_role_assignment` (BE-146).

Garde l'administrateur qui a révoqué une affectation, pour la traçabilité de
la révocation. Colonne ajoutée nullable : les lignes existantes, non révoquées,
restent valides. Le downgrade retire la colonne, donc l'information de qui a
révoqué ; les lignes ne sont jamais supprimées par cette migration.

Revision ID: b146c0de0146
Revises: 934346a13edd
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b146c0de0146"
down_revision: Union[str, None] = "934346a13edd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_role_assignment",
        sa.Column("revokedBy", sa.UUID(), nullable=True, comment="Administrateur ayant révoqué l'affectation (BE-146)."),
    )
    op.create_foreign_key(
        "fk_admin_role_assignment_revokedBy_user",
        "admin_role_assignment",
        "user",
        ["revokedBy"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_admin_role_assignment_revokedBy_user", "admin_role_assignment", type_="foreignkey")
    op.drop_column("admin_role_assignment", "revokedBy")
