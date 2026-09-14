"""sellable product simple stock

Revision ID: 9485538b2c45
Revises: f1a2b3c4d5e6
Create Date: 2026-09-13

Mission « Boutique Zylo Liquid » (Phase 4, décision validée : stock simple —
une quantité par produit×station, décrémentée à la vente, sans journal de
mouvements détaillé). Colonnes additives uniquement sur
`SellableProduct` — pas de nouvelle table.

Migration écrite à la main pour la même raison que
`69a55c682c0a_add_supplier_tax_id.py` (autogenerate mêle du bruit de
renommage d'index sans rapport).
"""

from alembic import op
import sqlalchemy as sa

revision = "9485538b2c45"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "zyloLiquidSellableProduct",
        sa.Column("stockQuantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "zyloLiquidSellableProduct",
        sa.Column("lowStockThreshold", sa.Numeric(14, 4), nullable=True),
    )
    op.alter_column("zyloLiquidSellableProduct", "stockQuantity", server_default=None)
    op.create_check_constraint(
        "ck_zlSellableProduct_stock_non_negative",
        "zyloLiquidSellableProduct",
        '"stockQuantity" >= 0',
    )


def downgrade() -> None:
    op.drop_constraint("ck_zlSellableProduct_stock_non_negative", "zyloLiquidSellableProduct", type_="check")
    op.drop_column("zyloLiquidSellableProduct", "lowStockThreshold")
    op.drop_column("zyloLiquidSellableProduct", "stockQuantity")
