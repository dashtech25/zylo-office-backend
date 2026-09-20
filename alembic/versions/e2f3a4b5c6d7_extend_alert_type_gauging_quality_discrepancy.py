"""extend alert type for manual gauging and quality check discrepancies

Revision ID: e2f3a4b5c6d7
Revises: c7d8e9f0a1b2
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "'level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
    "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
    "'price_missing','sensor_mapping_missing','calibration_missing','truck_stop_unqualified',"
    "'station_offline','stock_declared_discrepancy'"
)
NEW_TYPES = OLD_TYPES + ",'manual_gauging_discrepancy','quality_check_discrepancy'"


def upgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({NEW_TYPES})")


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({OLD_TYPES})")
