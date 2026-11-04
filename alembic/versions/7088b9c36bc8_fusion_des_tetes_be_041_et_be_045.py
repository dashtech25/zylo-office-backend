"""Fusion des tetes BE-041 et BE-045

Revision ID: 7088b9c36bc8
Revises: e041b7c3d9f2, a045b1c2d3e4
Create Date: 2026-11-04 00:58:50.398240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7088b9c36bc8'
down_revision: Union[str, None] = ('e041b7c3d9f2', 'a045b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
