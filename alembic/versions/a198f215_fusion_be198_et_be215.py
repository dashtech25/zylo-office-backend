"""Fusion des têtes BE-198 et BE-215 pour alembic.

Revision ID: a198f215
Revises: be198a0b1c2d, be215a1b2c3d
Create Date: 2026-11-12 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a198f215'
down_revision: Union[str, Sequence[str], None] = ('be198a0b1c2d', 'be215a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
