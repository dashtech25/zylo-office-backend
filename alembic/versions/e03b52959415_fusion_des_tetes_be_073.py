"""Fusion des tetes be-073

Revision ID: e03b52959415
Revises: a1d073b2c4e5, b56edb92fa23
Create Date: 2026-11-04 01:41:49.830914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e03b52959415'
down_revision: Union[str, None] = ('a1d073b2c4e5', 'b56edb92fa23')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
