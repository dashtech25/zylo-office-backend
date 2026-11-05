"""Fusion des têtes Alembic be-247 dans develop

Revision ID: f9d7ef17ec72
Revises: aab72f59d1c3, c247b1d2e3f4
Create Date: 2026-11-05 10:04:14.345022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9d7ef17ec72'
down_revision: Union[str, None] = ('aab72f59d1c3', 'c247b1d2e3f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
