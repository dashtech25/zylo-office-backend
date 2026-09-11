"""add supplier tax id

Revision ID: 69a55c682c0a
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10

Colonne additive uniquement — `Supplier.taxId` (SIRET/RCS), nécessaire au
bon de commande généré (mission « bon de commande + aperçu/partage »).
Migration écrite à la main : `alembic revision --autogenerate` mêle
systématiquement à ce diff un bruit important de renommage d'index sans
rapport (dérive préexistante déjà observée sur les migrations précédentes
de cette mission), jamais inclus ici.
"""

from alembic import op
import sqlalchemy as sa

revision = "69a55c682c0a"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zyloLiquidSupplier", sa.Column("taxId", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("zyloLiquidSupplier", "taxId")
