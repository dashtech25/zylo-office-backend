"""merge_be_126_and_develop_heads

Revision ID: 7b3cdbc1efc8
Revises: 9056fdbfa86f, b126a0de0126
Create Date: 2026-11-05 08:37:41.163030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b3cdbc1efc8'
down_revision: Union[str, None] = ('9056fdbfa86f', 'b126a0de0126')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
