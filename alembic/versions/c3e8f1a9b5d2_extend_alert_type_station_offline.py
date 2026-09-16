"""extend alert type for station offline (silence complet, P1-9 audit stations)

Revision ID: c3e8f1a9b5d2
Revises: a6c4753043f0
Create Date: 2026-09-16 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3e8f1a9b5d2'
down_revision: Union[str, None] = 'a6c4753043f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "'level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
    "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
    "'price_missing','sensor_mapping_missing','calibration_missing','truck_stop_unqualified'"
)
NEW_TYPES = OLD_TYPES + ",'station_offline'"


def upgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({NEW_TYPES})")


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({OLD_TYPES})")
