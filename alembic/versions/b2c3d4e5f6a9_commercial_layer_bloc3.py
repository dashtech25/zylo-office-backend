"""commercial_layer_bloc3

Revision ID: b2c3d4e5f6a9
Revises: a1b2c3d4e5f8
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a9'
down_revision: Union[str, None] = 'a1b2c3d4e5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return [
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'zyloLiquidCommercialAccount',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('creditLimit', sa.Numeric(14, 4), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index('ix_zlCommercialAccount_organizationId', 'zyloLiquidCommercialAccount', ['organizationId'])

    op.create_table(
        'zyloLiquidVehicle',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('plateOrReference', sa.String(length=50), nullable=False),
        *_timestamps(),
    )
    op.create_index('ix_zlVehicle_commercialAccountId', 'zyloLiquidVehicle', ['commercialAccountId'])

    op.create_table(
        'zyloLiquidDriver',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        *_timestamps(),
    )
    op.create_index('ix_zlDriver_commercialAccountId', 'zyloLiquidDriver', ['commercialAccountId'])

    op.create_table(
        'zyloLiquidAuthorization',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('vehicleId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidVehicle.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('driverId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDriver.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index('ix_zlAuthorization_commercialAccountId', 'zyloLiquidAuthorization', ['commercialAccountId'])

    op.create_table(
        'zyloLiquidSale',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('authorUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('eventAt', sa.DateTime(), nullable=False),
        sa.Column('fuelProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidFuelProduct.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantityLiters', sa.Numeric(12, 4), nullable=False),
        sa.Column('priceAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('paymentMethod', sa.String(length=10), nullable=False),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('vehicleId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidVehicle.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('driverId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDriver.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('declarationType', sa.String(length=40), nullable=True),
        sa.Column('declarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint('"paymentMethod" IN (\'cash\',\'card\',\'fleet\',\'credit\')', name='ck_zlSale_paymentMethod'),
        *_timestamps(),
    )
    op.create_index('ix_zlSale_stationId', 'zyloLiquidSale', ['stationId'])
    op.create_index('ix_zlSale_eventAt', 'zyloLiquidSale', ['eventAt'])
    op.create_index('ix_zlSale_commercialAccountId', 'zyloLiquidSale', ['commercialAccountId'])

    op.create_table(
        'zyloLiquidReceivable',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('saleId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidSale.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('amount', sa.Numeric(14, 4), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.CheckConstraint("status IN ('open','partially_settled','settled')", name='ck_zlReceivable_status'),
        *_timestamps(),
    )
    op.create_index('ix_zlReceivable_commercialAccountId', 'zyloLiquidReceivable', ['commercialAccountId'])
    op.create_index('ix_zlReceivable_saleId', 'zyloLiquidReceivable', ['saleId'])

    op.create_table(
        'zyloLiquidPayment',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('receivableId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidReceivable.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('authorUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('paidAt', sa.DateTime(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 4), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('exchangeRateApplied', sa.Numeric(18, 8), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=True),
        *_timestamps(),
    )
    op.create_index('ix_zlPayment_receivableId', 'zyloLiquidPayment', ['receivableId'])


def downgrade() -> None:
    op.drop_table('zyloLiquidPayment')
    op.drop_table('zyloLiquidReceivable')
    op.drop_table('zyloLiquidSale')
    op.drop_table('zyloLiquidAuthorization')
    op.drop_table('zyloLiquidDriver')
    op.drop_table('zyloLiquidVehicle')
    op.drop_table('zyloLiquidCommercialAccount')
