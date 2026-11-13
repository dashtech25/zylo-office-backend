"""fusion tetes be255

Revision ID: f2559e1a2b3c
Revises: e0941f2a3b4c, a7c25e5b1d03
Create Date: 2026-11-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2559e1a2b3c'
down_revision: Union[str, None] = ('e0941f2a3b4c', 'a7c25e5b1d03')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
