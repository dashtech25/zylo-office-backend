"""fusion tetes be142

Revision ID: d1421e7f0a3b
Revises: c2394d7a1b90, e142a5c0d142
Create Date: 2026-11-05 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1421e7f0a3b'
down_revision: Union[str, None] = ('c2394d7a1b90', 'e142a5c0d142')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
