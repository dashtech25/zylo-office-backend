"""sale shift start

Revision ID: 1c6f436f3b4d
Revises: f3a4b5c6d7e8
Create Date: 2026-09-25

Colonne additive uniquement — `Sale.shiftStart` (début de shift déclaré,
`eventAt` reste la fin de shift), nécessaire à la grille de déclaration de
ventes multi-lignes (maquette validée 2026-09-25). Migration écrite à la
main : `alembic revision --autogenerate` mêle systématiquement à ce diff
un bruit important de renommage d'index sans rapport (dérive préexistante
déjà observée sur les migrations précédentes de cette mission), jamais
inclus ici.
"""

from alembic import op
import sqlalchemy as sa

revision = "1c6f436f3b4d"
down_revision = "7c2e9a1f4b8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zyloLiquidSale", sa.Column("shiftStart", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("zyloLiquidSale", "shiftStart")
