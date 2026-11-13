"""Fusion des tetes be-046

Revision ID: 22365035629c
Revises: 19f753807bd6, b046a1e2c3d4
Create Date: 2026-11-04 01:37:27.671768

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22365035629c'
down_revision: Union[str, None] = ('19f753807bd6', 'b046a1e2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
