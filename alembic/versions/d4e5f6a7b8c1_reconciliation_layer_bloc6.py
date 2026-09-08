"""reconciliation_layer_bloc6

Revision ID: d4e5f6a7b8c1
Revises: c3d4e5f6a7b0
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c1'
down_revision: Union[str, None] = 'c3d4e5f6a7b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zyloLiquidStationReconciliationSettings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('deliveryWindowHours', sa.Numeric(6, 2), nullable=True),
        sa.Column('deliveryVolumeToleranceFixedLiters', sa.Numeric(10, 2), nullable=True),
        sa.Column('deliveryVolumeTolerancePercent', sa.Numeric(5, 2), nullable=True),
        sa.Column('gaugingHeightToleranceMm', sa.Numeric(6, 2), nullable=True),
        sa.Column('qualityCheckWindowHours', sa.Numeric(6, 2), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('stationId', name='uq_zlStationReconciliationSettings_station'),
    )

    op.create_table(
        'zyloLiquidReconciliationRecord',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('subjectType', sa.String(length=40), nullable=False),
        sa.Column('subjectId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('counterpartType', sa.String(length=40), nullable=True),
        # String, jamais UUID : TankMeasurement.id (contrepartie du
        # rapprochement de jaugeage manuel) est un entier auto-incrémenté.
        sa.Column('counterpartId', sa.String(length=64), nullable=True),
        sa.Column('family', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('discrepancyValue', sa.Numeric(14, 4), nullable=True),
        sa.Column('discrepancyUnit', sa.String(length=20), nullable=True),
        sa.Column('toleranceApplied', sa.Numeric(14, 4), nullable=True),
        sa.Column('evaluatedAt', sa.DateTime(), nullable=False),
        sa.Column('evaluatedByUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("family IN ('quantitative','consistency')", name='ck_zlReconciliationRecord_family'),
        sa.CheckConstraint("status IN ('matched','discrepancy','pending','insufficient_data')", name='ck_zlReconciliationRecord_status'),
    )
    op.create_index('ix_zlReconciliationRecord_subjectType', 'zyloLiquidReconciliationRecord', ['subjectType'])
    op.create_index('ix_zlReconciliationRecord_subjectId', 'zyloLiquidReconciliationRecord', ['subjectId'])
    op.create_index('ix_zlReconciliationRecord_evaluatedAt', 'zyloLiquidReconciliationRecord', ['evaluatedAt'])


def downgrade() -> None:
    op.drop_table('zyloLiquidReconciliationRecord')
    op.drop_table('zyloLiquidStationReconciliationSettings')
