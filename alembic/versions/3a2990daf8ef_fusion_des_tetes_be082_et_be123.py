"""fusion des tetes be082 et be123

Revision ID: 3a2990daf8ef
Revises: a123c0de0123, b082a1c2d3e4
Create Date: 2026-11-05 05:11:38.841399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a2990daf8ef'
down_revision: Union[str, None] = ('a123c0de0123', 'b082a1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
