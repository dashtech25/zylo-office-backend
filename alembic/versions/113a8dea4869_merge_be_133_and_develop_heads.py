"""merge be_133 and develop heads

Revision ID: 113a8dea4869
Revises: c133e2f4a133, f32497e0328e
Create Date: 2026-11-05 08:32:21.981120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '113a8dea4869'
down_revision: Union[str, None] = ('c133e2f4a133', 'f32497e0328e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
