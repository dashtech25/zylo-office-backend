"""fusion be-161 et be-128

Revision ID: 495a7fcdc066
Revises: 7a2c9d1e4f60, be128a0de0128
Create Date: 2026-11-05 06:39:35.821196

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '495a7fcdc066'
down_revision: Union[str, None] = ('7a2c9d1e4f60', 'be128a0de0128')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
