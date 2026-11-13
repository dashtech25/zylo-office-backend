"""fusion BE-202 et develop

Revision ID: 90f0db41ebb6
Revises: b211a0c1d2e3, be202d3e4f5a
Create Date: 2026-11-07 14:33:35.113897

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90f0db41ebb6'
down_revision: Union[str, None] = ('b211a0c1d2e3', 'be202d3e4f5a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
