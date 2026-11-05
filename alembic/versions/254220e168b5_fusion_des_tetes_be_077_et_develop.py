"""Fusion des tetes be-077 et develop

Revision ID: 254220e168b5
Revises: c6cd5d6c8c35, f077a1b2c3d4
Create Date: 2026-11-05 03:44:28.726628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '254220e168b5'
down_revision: Union[str, None] = ('c6cd5d6c8c35', 'f077a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
