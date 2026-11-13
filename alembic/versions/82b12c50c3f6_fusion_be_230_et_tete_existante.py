"""fusion be-230 et tete existante

Revision ID: 82b12c50c3f6
Revises: 9a075a4572eb, be230a1b2c3d
Create Date: 2026-11-03 23:11:44.503999

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82b12c50c3f6'
down_revision: Union[str, None] = ('9a075a4572eb', 'be230a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
