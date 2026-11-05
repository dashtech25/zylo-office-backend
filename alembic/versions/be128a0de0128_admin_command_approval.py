"""Table des décisions d'approbation de commandes opérateur (BE-128).

Revision ID: be128a0de0128
Revises: 5e31981cf46c
Create Date: 2026-11-05

Ajoute `admin_command_approval` (une décision par commande, clé primaire `commandId`)
et élargit la contrainte `ck_admin_command_status` aux états terminaux `approuvee`
et `rejetee`.

Downgrade : les commandes décidées repassent à `intention` avec `approverId` NULL, et
leurs lignes de décision sont supprimées. Cette réversion perd l'historique des
décisions ; elle n'est à utiliser qu'en local ou sur une base de test.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "be128a0de0128"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_admin_command_status", "admin_command", type_="check")
    op.create_check_constraint(
        "ck_admin_command_status",
        "admin_command",
        "status IN ('intention', 'approuvee', 'rejetee')",
    )
    op.create_table(
        "admin_command_approval",
        sa.Column("commandId", sa.UUID(), nullable=False),
        sa.Column("approverId", sa.UUID(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decidedAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reasonTicket", sa.String(length=120), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approuvee', 'rejetee')", name="ck_admin_command_approval_decision",
        ),
        sa.ForeignKeyConstraint(["commandId"], ["admin_command.commandId"]),
        sa.ForeignKeyConstraint(["approverId"], ["user.id"]),
        sa.PrimaryKeyConstraint("commandId"),
        comment="Décision unique d'un approbateur indépendant sur une commande opérateur (BE-128).",
    )
    op.create_index("ix_admin_command_approval_approverId", "admin_command_approval", ["approverId"])


def downgrade() -> None:
    op.execute(
        "DELETE FROM admin_command_approval WHERE \"commandId\" IN "
        "(SELECT \"commandId\" FROM admin_command WHERE status IN ('approuvee', 'rejetee'))"
    )
    op.execute(
        "UPDATE admin_command SET status = 'intention', \"approverId\" = NULL "
        "WHERE status IN ('approuvee', 'rejetee')"
    )
    op.drop_index("ix_admin_command_approval_approverId", table_name="admin_command_approval")
    op.drop_table("admin_command_approval")
    op.drop_constraint("ck_admin_command_status", "admin_command", type_="check")
    op.create_check_constraint(
        "ck_admin_command_status", "admin_command", "status IN ('intention')",
    )
