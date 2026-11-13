"""fusion BE-213 et develop

Revision ID: 02a46cdda276
Revises: b103c0de0103, c213a1b2c3d4
Create Date: 2026-11-06 06:21:05.389115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02a46cdda276'
down_revision: Union[str, None] = ('b103c0de0103', 'c213a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
