"""BE-167 : catégories et règles de notification

Revision ID: 7c3e9d2b4a10
Revises: 5e31981cf46c
Create Date: 2026-11-05 10:00:00.000000

Crée `categorie_notification` (clé `code`, audience obligatoire, canal NULL par défaut)
et `regle_notification` (événement vers catégorie et audience). Downgrade : suppression
des deux tables, la règle d'abord (clé étrangère).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7c3e9d2b4a10"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categorie_notification",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("libelle", sa.String(length=200), nullable=False),
        sa.Column("audienceRegle", sa.String(length=120), nullable=False),
        sa.Column("canalDefaut", sa.String(length=40), nullable=True),
        sa.Column("actif", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint('length(btrim("audienceRegle")) > 0', name="ck_categorie_notification_audience_non_vide"),
        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_categorie_notification_code_non_vide"),
        sa.PrimaryKeyConstraint("code"),
        comment="Catégories de notification et leur audience (BE-167), sans canal présumé.",
    )
    op.create_table(
        "regle_notification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("evenementType", sa.String(length=150), nullable=False),
        sa.Column("categorieCode", sa.String(length=80), nullable=False),
        sa.Column("audience", sa.String(length=120), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["categorieCode"], ["categorie_notification.code"], name="fk_regle_notification_categorie", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evenementType", "categorieCode", name="uq_regle_notification_evenement_categorie"),
        comment="Règles événement vers catégorie et audience (BE-167), configurées par la plateforme.",
    )
    op.create_index("ix_regle_notification_evenementType", "regle_notification", ["evenementType"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_regle_notification_evenementType", table_name="regle_notification")
    op.drop_table("regle_notification")
    op.drop_table("categorie_notification")
