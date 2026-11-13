"""Fusion des tetes be-079

Revision ID: 169de7fb56af
Revises: b8fbeeea5dd5, e079a1b2c3d4
Create Date: 2026-11-04 01:44:33.380736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '169de7fb56af'
down_revision: Union[str, None] = ('b8fbeeea5dd5', 'e079a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
