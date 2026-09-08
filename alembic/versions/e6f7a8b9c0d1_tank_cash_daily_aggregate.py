"""tank_cash_daily_aggregate

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zyloLiquidTankCashDailyAggregate',
        sa.Column('tankId', sa.UUID(), nullable=False),
        sa.Column('cashDate', sa.Date(), nullable=False),
        sa.Column('volumeSoldLiters', sa.Numeric(14, 4), nullable=True),
        sa.Column('volumeNotCalculableReason', sa.String(50), nullable=True),
        sa.Column('monetaryValue', sa.Numeric(16, 4), nullable=True),
        sa.Column('currencyCode', sa.String(3), nullable=True),
        sa.Column('monetaryValueNotCalculableReason', sa.String(50), nullable=True),
        sa.Column('confidence', sa.String(20), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tankId'], ['zyloLiquidTank.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tankId', 'cashDate', name='uq_zlTankCashDailyAggregate_tank_date'),
        comment="Cache des totaux de caisse par cuve et par jour clos — jamais la source de vérité, un recalcul reste toujours possible.",
    )
    op.create_index(op.f('ix_zyloLiquidTankCashDailyAggregate_tankId'), 'zyloLiquidTankCashDailyAggregate', ['tankId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidTankCashDailyAggregate_cashDate'), 'zyloLiquidTankCashDailyAggregate', ['cashDate'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zyloLiquidTankCashDailyAggregate_cashDate'), table_name='zyloLiquidTankCashDailyAggregate')
    op.drop_index(op.f('ix_zyloLiquidTankCashDailyAggregate_tankId'), table_name='zyloLiquidTankCashDailyAggregate')
    op.drop_table('zyloLiquidTankCashDailyAggregate')
