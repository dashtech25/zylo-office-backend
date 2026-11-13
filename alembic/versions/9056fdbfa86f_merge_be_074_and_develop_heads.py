"""merge_be_074_and_develop_heads

Revision ID: 9056fdbfa86f
Revises: 113a8dea4869, a074b1c2d3e4
Create Date: 2026-11-05 08:36:30.388190

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9056fdbfa86f'
down_revision: Union[str, None] = ('113a8dea4869', 'a074b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
