"""station_currency_override

Revision ID: a2b3c4d5e6f7
Revises: e1a2b3c4d5f6
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidStation', sa.Column('currencyOverrideId', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_zlStation_currencyOverrideId_currency',
        'zyloLiquidStation', 'currency',
        ['currencyOverrideId'], ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    op.drop_constraint('fk_zlStation_currencyOverrideId_currency', 'zyloLiquidStation', type_='foreignkey')
    op.drop_column('zyloLiquidStation', 'currencyOverrideId')
