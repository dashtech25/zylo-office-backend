"""sellable product image + per-station price history (boutique)

Revision ID: 1047562d0691
Revises: f4a7c2d891be
Create Date: 2026-09-17 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1047562d0691'
# Base sur la révision actuellement appliquée en base (f4a7c2d891be), pas sur
# le head courant des fichiers versions/ : une autre session a un fichier de
# migration non commité/non appliqué (d1e2f3a4b5c6, tracking navires Zylo
# Tanker) branché sur le même head — éviter tout couplage avec ce travail en
# cours d'une autre session, la fusion des deux branches se fera séparément.
down_revision: Union[str, None] = 'f4a7c2d891be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidSellableProduct', sa.Column('imageStorageReference', sa.Text(), nullable=True))

    op.create_table(
        'zyloLiquidSellableProductPrice',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('createdAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updatedAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('sellableProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidSellableProduct.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('priceAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('costAmount', sa.Numeric(14, 4), nullable=True),
        sa.Column('effectiveFrom', sa.DateTime(), nullable=False),
        sa.Column('changeReason', sa.Text(), nullable=True),
        sa.Column('createdBy', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.CheckConstraint('"priceAmount" > 0', name='ck_zlSellableProductPrice_priceAmount_positive'),
        sa.UniqueConstraint('stationId', 'sellableProductId', 'effectiveFrom', name='uq_zlSellableProductPrice_station_product_effectiveFrom'),
        comment='Historique des prix des produits boutique — changement réel = insertion, correction = UPDATE ciblé.',
    )
    op.create_index('ix_zlSellableProductPrice_stationId', 'zyloLiquidSellableProductPrice', ['stationId'])
    op.create_index('ix_zlSellableProductPrice_sellableProductId', 'zyloLiquidSellableProductPrice', ['sellableProductId'])
    op.create_index('ix_zlSellableProductPrice_effectiveFrom', 'zyloLiquidSellableProductPrice', ['effectiveFrom'])
    op.create_index(
        'uq_zlSellableProductPrice_networkDefault_product_effectiveFrom',
        'zyloLiquidSellableProductPrice',
        ['sellableProductId', 'currencyId', 'effectiveFrom'],
        unique=True,
        postgresql_where=sa.text('"stationId" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_zlSellableProductPrice_networkDefault_product_effectiveFrom', table_name='zyloLiquidSellableProductPrice')
    op.drop_index('ix_zlSellableProductPrice_effectiveFrom', table_name='zyloLiquidSellableProductPrice')
    op.drop_index('ix_zlSellableProductPrice_sellableProductId', table_name='zyloLiquidSellableProductPrice')
    op.drop_index('ix_zlSellableProductPrice_stationId', table_name='zyloLiquidSellableProductPrice')
    op.drop_table('zyloLiquidSellableProductPrice')
    op.drop_column('zyloLiquidSellableProduct', 'imageStorageReference')
