"""Fusion des têtes Alembic be-253 dans develop

Revision ID: fd57ba293e8b
Revises: 05aa53c71fa5, c253a1b2d3e4
Create Date: 2026-11-05 10:23:40.964141

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd57ba293e8b'
down_revision: Union[str, None] = ('05aa53c71fa5', 'c253a1b2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
