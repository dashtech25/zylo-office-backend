"""declarative_layer_bloc1

Revision ID: a1b2c3d4e5f8
Revises: f1a2b3c4d5e7
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f8'
down_revision: Union[str, None] = 'f1a2b3c4d5e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Colonne camelCase avec majuscule interne : doit être citée entre
# guillemets doubles dans le texte brut d'un CheckConstraint, sinon
# PostgreSQL la traite comme "lifecyclestatus" (tout en minuscules) et
# lève UndefinedColumnError à la création de la table.
LIFECYCLE_CHECK = '"lifecycleStatus" IN (\'declared\',\'locked\')'


def _common_columns():
    return [
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('authorUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('eventAt', sa.DateTime(), nullable=False),
        sa.Column('declaredAt', sa.DateTime(), nullable=False),
        sa.Column('lifecycleStatus', sa.String(length=10), nullable=False, server_default='declared'),
        sa.Column('changeReason', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'zyloLiquidDeliveryDeclaration',
        *_common_columns(),
        sa.Column('fuelProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidFuelProduct.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('supplierName', sa.String(length=150), nullable=True),
        sa.Column('declaredVolumeLiters', sa.Numeric(12, 4), nullable=False),
        sa.Column('deliveryNoteReference', sa.String(length=100), nullable=True),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlDeliveryDeclaration_lifecycleStatus'),
    )
    op.create_foreign_key('fk_zlDeliveryDeclaration_corrects', 'zyloLiquidDeliveryDeclaration', 'zyloLiquidDeliveryDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlDeliveryDeclaration_stationId', 'zyloLiquidDeliveryDeclaration', ['stationId'])
    op.create_index('ix_zlDeliveryDeclaration_eventAt', 'zyloLiquidDeliveryDeclaration', ['eventAt'])
    op.create_index('ix_zlDeliveryDeclaration_fuelProductId', 'zyloLiquidDeliveryDeclaration', ['fuelProductId'])

    op.create_table(
        'zyloLiquidShiftCashDeclaration',
        *_common_columns(),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('shiftStart', sa.DateTime(), nullable=False),
        sa.Column('shiftEnd', sa.DateTime(), nullable=False),
        sa.Column('openingReadingMm', sa.Numeric(10, 2), nullable=True),
        sa.Column('closingReadingMm', sa.Numeric(10, 2), nullable=True),
        sa.Column('declaredCashAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlShiftCashDeclaration_lifecycleStatus'),
    )
    op.create_foreign_key('fk_zlShiftCashDeclaration_corrects', 'zyloLiquidShiftCashDeclaration', 'zyloLiquidShiftCashDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlShiftCashDeclaration_stationId', 'zyloLiquidShiftCashDeclaration', ['stationId'])
    op.create_index('ix_zlShiftCashDeclaration_eventAt', 'zyloLiquidShiftCashDeclaration', ['eventAt'])
    op.create_index('ix_zlShiftCashDeclaration_tankId', 'zyloLiquidShiftCashDeclaration', ['tankId'])

    op.create_table(
        'zyloLiquidManualGaugingDeclaration',
        *_common_columns(),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('declaredHeightMm', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlManualGaugingDeclaration_lifecycleStatus'),
        sa.CheckConstraint("method IN ('dipstick','gauge_pole','other')", name='ck_zlManualGaugingDeclaration_method'),
    )
    op.create_foreign_key('fk_zlManualGaugingDeclaration_corrects', 'zyloLiquidManualGaugingDeclaration', 'zyloLiquidManualGaugingDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlManualGaugingDeclaration_stationId', 'zyloLiquidManualGaugingDeclaration', ['stationId'])
    op.create_index('ix_zlManualGaugingDeclaration_eventAt', 'zyloLiquidManualGaugingDeclaration', ['eventAt'])
    op.create_index('ix_zlManualGaugingDeclaration_tankId', 'zyloLiquidManualGaugingDeclaration', ['tankId'])

    op.create_table(
        'zyloLiquidQualityCheckDeclaration',
        *_common_columns(),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('waterDetected', sa.Boolean(), nullable=False),
        sa.Column('waterHeightMm', sa.Numeric(10, 2), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlQualityCheckDeclaration_lifecycleStatus'),
        sa.CheckConstraint("method IN ('dipstick','water_paste','other')", name='ck_zlQualityCheckDeclaration_method'),
    )
    op.create_foreign_key('fk_zlQualityCheckDeclaration_corrects', 'zyloLiquidQualityCheckDeclaration', 'zyloLiquidQualityCheckDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlQualityCheckDeclaration_stationId', 'zyloLiquidQualityCheckDeclaration', ['stationId'])
    op.create_index('ix_zlQualityCheckDeclaration_eventAt', 'zyloLiquidQualityCheckDeclaration', ['eventAt'])
    op.create_index('ix_zlQualityCheckDeclaration_tankId', 'zyloLiquidQualityCheckDeclaration', ['tankId'])

    op.create_table(
        'zyloLiquidLeakTestDeclaration',
        *_common_columns(),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('result', sa.String(length=10), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlLeakTestDeclaration_lifecycleStatus'),
        sa.CheckConstraint("result IN ('normal','anomaly')", name='ck_zlLeakTestDeclaration_result'),
    )
    op.create_foreign_key('fk_zlLeakTestDeclaration_corrects', 'zyloLiquidLeakTestDeclaration', 'zyloLiquidLeakTestDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlLeakTestDeclaration_stationId', 'zyloLiquidLeakTestDeclaration', ['stationId'])
    op.create_index('ix_zlLeakTestDeclaration_eventAt', 'zyloLiquidLeakTestDeclaration', ['eventAt'])
    op.create_index('ix_zlLeakTestDeclaration_tankId', 'zyloLiquidLeakTestDeclaration', ['tankId'])

    op.create_table(
        'zyloLiquidIncidentDeclaration',
        *_common_columns(),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('correctsDeclarationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(length=40), nullable=True),
        sa.CheckConstraint(LIFECYCLE_CHECK, name='ck_zlIncidentDeclaration_lifecycleStatus'),
        sa.CheckConstraint("category IN ('safety','equipment','quality','security','other')", name='ck_zlIncidentDeclaration_category'),
    )
    op.create_foreign_key('fk_zlIncidentDeclaration_corrects', 'zyloLiquidIncidentDeclaration', 'zyloLiquidIncidentDeclaration', ['correctsDeclarationId'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_zlIncidentDeclaration_stationId', 'zyloLiquidIncidentDeclaration', ['stationId'])
    op.create_index('ix_zlIncidentDeclaration_eventAt', 'zyloLiquidIncidentDeclaration', ['eventAt'])
    op.create_index('ix_zlIncidentDeclaration_tankId', 'zyloLiquidIncidentDeclaration', ['tankId'])


def downgrade() -> None:
    op.drop_table('zyloLiquidIncidentDeclaration')
    op.drop_table('zyloLiquidLeakTestDeclaration')
    op.drop_table('zyloLiquidQualityCheckDeclaration')
    op.drop_table('zyloLiquidManualGaugingDeclaration')
    op.drop_table('zyloLiquidShiftCashDeclaration')
    op.drop_table('zyloLiquidDeliveryDeclaration')
