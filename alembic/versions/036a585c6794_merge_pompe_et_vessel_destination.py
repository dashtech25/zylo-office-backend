"""merge pompe et vessel destination

Revision ID: 036a585c6794
Revises: a3c8f1d2e4b7, d1e2f3a4b5c6
Create Date: 2026-09-17 22:06:55.502333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '036a585c6794'
down_revision: Union[str, None] = ('a3c8f1d2e4b7', 'd1e2f3a4b5c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
