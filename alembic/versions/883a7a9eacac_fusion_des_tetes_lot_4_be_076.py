"""Fusion des tetes lot 4 be-076

Revision ID: 883a7a9eacac
Revises: 2b2ba311c93c, c076a1b2c3d4
Create Date: 2026-11-04 02:15:34.698669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '883a7a9eacac'
down_revision: Union[str, None] = ('2b2ba311c93c', 'c076a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
