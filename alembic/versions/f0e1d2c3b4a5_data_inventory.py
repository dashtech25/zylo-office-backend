"""Inventaire des données : table data_inventory (BE-242).

Objectif : créer le registre qui décrit, champ par champ, la classe, le
propriétaire, la rétention et les modalités de sauvegarde, export et suppression.
Migration purement additive : aucune donnée existante n'est modifiée.

Réversibilité : downgrade() supprime la table. Le registre n'est pas une donnée
métier ; sa suppression n'efface aucune donnée utilisateur.
"""

import sqlalchemy as sa
from alembic import op

revision = "f0e1d2c3b4a5"
down_revision = "b7c8d9e0f123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_inventory",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("objet", sa.String(length=150), nullable=False),
        sa.Column("champ", sa.String(length=150), nullable=False),
        sa.Column("finalite", sa.String(length=300), nullable=True),
        sa.Column("classe", sa.String(length=50), nullable=True),
        sa.Column("tenantScope", sa.String(length=20), nullable=True),
        sa.Column("proprietaire", sa.String(length=100), nullable=True),
        sa.Column("lecteurs", sa.String(length=300), nullable=True),
        sa.Column("transfert", sa.String(length=300), nullable=True),
        sa.Column("retentionJours", sa.Integer(), nullable=True),
        sa.Column("sauvegarde", sa.String(length=100), nullable=True),
        sa.Column("export", sa.String(length=100), nullable=True),
        sa.Column("suppression", sa.String(length=300), nullable=True),
        sa.UniqueConstraint("objet", "champ", name="uq_data_inventory_objet_champ"),
        comment="Inventaire des données : classe, propriétaire, rétention et modalités par champ.",
    )


def downgrade() -> None:
    op.drop_table("data_inventory")
