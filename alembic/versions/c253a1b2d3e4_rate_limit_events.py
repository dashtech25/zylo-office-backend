"""BE-253 : table rate_limit_events (compteurs de limites d'usage)

Revision ID: c253a1b2d3e4
Revises: 290f30a9bcbf
Create Date: 2026-11-05

Table de compteurs à fenêtre fixe : une ligne par (clé hachée, début de fenêtre).
Ajout pur, sans donnée existante à reprendre. Downgrade : suppression de la table,
qui ne contient que des compteurs éphémères (aucune donnée métier).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c253a1b2d3e4"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("cle", sa.String(length=64), nullable=False, comment="Empreinte SHA-256 de (portée, tenant, identité)"),
        sa.Column("fenetre", sa.DateTime(timezone=True), nullable=False, comment="Début de la fenêtre, UTC"),
        sa.Column("compteur", sa.Integer(), nullable=False, comment="Requêtes comptées dans la fenêtre"),
        sa.PrimaryKeyConstraint("cle", "fenetre"),
        comment="Compteurs de limites d'usage par clé et fenêtre (BE-253). Empreintes uniquement.",
    )


def downgrade() -> None:
    op.drop_table("rate_limit_events")
