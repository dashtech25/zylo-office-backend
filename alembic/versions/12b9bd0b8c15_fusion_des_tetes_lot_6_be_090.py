"""Fusion des tetes lot 6 be-090

Revision ID: 12b9bd0b8c15
Revises: a090c1d2e3f4, a60bbc64035d
Create Date: 2026-11-04 02:18:27.297331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12b9bd0b8c15'
down_revision: Union[str, None] = ('a090c1d2e3f4', 'a60bbc64035d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
