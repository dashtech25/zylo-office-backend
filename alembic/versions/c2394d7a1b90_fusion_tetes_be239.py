"""fusion tetes be239

Revision ID: c2394d7a1b90
Revises: 84a44229c0d1, be239a1b2c3d
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2394d7a1b90'
down_revision: Union[str, None] = ('84a44229c0d1', 'be239a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
