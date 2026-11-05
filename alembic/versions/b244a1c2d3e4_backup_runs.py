"""Table backup_runs : preuve de génération des sauvegardes (BE-244).

Revision ID: b244a1c2d3e4
Revises: 290f30a9bcbf
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b244a1c2d3e4"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("horodatage", sa.DateTime(timezone=True), nullable=False),
        sa.Column("perimetre", sa.String(length=40), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("resultat", sa.String(length=20), nullable=False),
        sa.Column("empreinte", sa.String(length=64), nullable=True),
        sa.Column("emplacement", sa.String(length=120), nullable=True),
        sa.Column("chiffrement", sa.Boolean(), nullable=False),
        sa.CheckConstraint("resultat IN ('reussie','echec')", name="ck_backup_runs_resultat"),
        sa.PrimaryKeyConstraint("id"),
        comment="Tentatives de sauvegarde de la base de plateforme, avec résultat et empreinte (BE-244).",
    )


def downgrade() -> None:
    op.drop_table("backup_runs")
