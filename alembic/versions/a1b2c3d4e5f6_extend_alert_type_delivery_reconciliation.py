"""extend alert type for delivery reconciliation

Revision ID: a1b2c3d4e5f6
Revises: 9a4f0756e846
Create Date: 2026-09-10 09:45:37.019566

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9a4f0756e846'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = "'level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline'"
NEW_TYPES = OLD_TYPES + ",'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending'"


def upgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({NEW_TYPES})")


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint('ck_zlAlert_type', 'zyloLiquidAlert', f"type IN ({OLD_TYPES})")
