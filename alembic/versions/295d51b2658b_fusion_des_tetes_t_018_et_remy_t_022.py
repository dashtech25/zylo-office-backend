"""fusion des tetes T-018 et remy (T-022)

Revision ID: 295d51b2658b
Revises: a7d3c1e9f024, a9b8c7d6e5f4
Create Date: 2026-10-09 03:29:12.220453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '295d51b2658b'
down_revision: Union[str, None] = ('a7d3c1e9f024', 'a9b8c7d6e5f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
