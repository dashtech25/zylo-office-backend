"""fusion tetes be159

Revision ID: 84a44229c0d1
Revises: 159b5e0a7c31, 171b683326dd
Create Date: 2026-11-05 10:38:59.079709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84a44229c0d1'
down_revision: Union[str, None] = ('159b5e0a7c31', '171b683326dd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
