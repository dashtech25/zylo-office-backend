"""Fusion des tetes be-056

Revision ID: b56edb92fa23
Revises: 22365035629c, a056b1c2d3e4
Create Date: 2026-11-04 01:40:06.444273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b56edb92fa23'
down_revision: Union[str, None] = ('22365035629c', 'a056b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
