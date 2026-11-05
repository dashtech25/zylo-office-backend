"""fusion tetes be-124 et develop

Revision ID: 6d8693f9201f
Revises: c124a0de0124, e1b89dfe1796
Create Date: 2026-11-05 05:44:18.811752

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d8693f9201f'
down_revision: Union[str, None] = ('c124a0de0124', 'e1b89dfe1796')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
