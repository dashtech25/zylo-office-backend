"""extend alert type for stock declared discrepancy

Revision ID: c7d8e9f0a1b2
Revises: 84267b062f81
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = '84267b062f81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "'level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
    "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
    "'price_missing','sensor_mapping_missing','calibration_missing','truck_stop_unqualified',"
    "'station_offline'"
)
NEW_TYPES = OLD_TYPES + ",'stock_declared_discrepancy'"


def upgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({NEW_TYPES})")


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({OLD_TYPES})")
