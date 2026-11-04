"""Fusion des tetes be-055 et be-044 lot 3

Revision ID: 2b2ba311c93c
Revises: be055a1b2c3d, d4a8f2c1b9e0
Create Date: 2026-11-04 02:13:54.932738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b2ba311c93c'
down_revision: Union[str, None] = ('be055a1b2c3d', 'd4a8f2c1b9e0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
