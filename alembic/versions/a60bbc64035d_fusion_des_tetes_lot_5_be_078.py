"""Fusion des tetes lot 5 be-078

Revision ID: a60bbc64035d
Revises: 883a7a9eacac, c078a1b2d3e4
Create Date: 2026-11-04 02:17:45.393299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a60bbc64035d'
down_revision: Union[str, None] = ('883a7a9eacac', 'c078a1b2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
