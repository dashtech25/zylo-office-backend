"""Fusion des tetes be-042

Revision ID: 19f753807bd6
Revises: 7bbd625df9ad, c042a1b2d3e4
Create Date: 2026-11-04 01:35:51.745451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19f753807bd6'
down_revision: Union[str, None] = ('7bbd625df9ad', 'c042a1b2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
