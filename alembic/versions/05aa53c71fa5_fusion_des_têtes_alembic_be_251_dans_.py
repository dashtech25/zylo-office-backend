"""Fusion des têtes Alembic be-251 dans develop

Revision ID: 05aa53c71fa5
Revises: 3e7a1b2c9d41, f9d7ef17ec72
Create Date: 2026-11-05 10:20:40.025017

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05aa53c71fa5'
down_revision: Union[str, None] = ('3e7a1b2c9d41', 'f9d7ef17ec72')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
