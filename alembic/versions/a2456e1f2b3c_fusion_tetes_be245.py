"""fusion tetes be245

Revision ID: a2456e1f2b3c
Revises: f2559e1a2b3c, e245a1b2c3d4
Create Date: 2026-11-05 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2456e1f2b3c'
down_revision: Union[str, None] = ('f2559e1a2b3c', 'e245a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
