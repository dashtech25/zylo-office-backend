"""station_fuel_product

Revision ID: e1a2b3c4d5f6
Revises: b41b805c3119
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, None] = 'b41b805c3119'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('zyloLiquidStationFuelProduct',
    sa.Column('stationId', sa.UUID(), nullable=False),
    sa.Column('fuelProductId', sa.UUID(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fuelProductId'], ['zyloLiquidFuelProduct.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['stationId'], ['zyloLiquidStation.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stationId', 'fuelProductId', name='uq_zlStationFuelProduct_station_product'),
    comment="Association explicite « ce produit est vendu dans cette station » — jamais déduite implicitement d'une cuve ou d'un prix existant (page_configuration.md §15/§41)."
    )
    op.create_index(op.f('ix_zyloLiquidStationFuelProduct_stationId'), 'zyloLiquidStationFuelProduct', ['stationId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidStationFuelProduct_fuelProductId'), 'zyloLiquidStationFuelProduct', ['fuelProductId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zyloLiquidStationFuelProduct_fuelProductId'), table_name='zyloLiquidStationFuelProduct')
    op.drop_index(op.f('ix_zyloLiquidStationFuelProduct_stationId'), table_name='zyloLiquidStationFuelProduct')
    op.drop_table('zyloLiquidStationFuelProduct')
