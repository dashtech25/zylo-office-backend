"""price_history_network_default

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('zyloLiquidPriceHistory', 'stationId', nullable=True)
    op.create_index(
        'uq_zlPriceHistory_networkDefault_product_effectiveFrom',
        'zyloLiquidPriceHistory',
        ['fuelProductId', 'effectiveFrom'],
        unique=True,
        postgresql_where=sa.text('"stationId" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_zlPriceHistory_networkDefault_product_effectiveFrom', table_name='zyloLiquidPriceHistory')
    op.alter_column('zyloLiquidPriceHistory', 'stationId', nullable=False)
