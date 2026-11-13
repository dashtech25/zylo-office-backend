"""fusion tetes be094

Revision ID: e0941f2a3b4c
Revises: d1421e7f0a3b, e094a1c2d3e4
Create Date: 2026-11-05 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0941f2a3b4c'
down_revision: Union[str, None] = ('d1421e7f0a3b', 'e094a1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
