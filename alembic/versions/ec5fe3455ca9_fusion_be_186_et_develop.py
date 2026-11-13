"""fusion BE-186 et develop

Revision ID: ec5fe3455ca9
Revises: c9d8e7f6a5b4, d186a0c1e2f3
Create Date: 2026-11-06 05:15:48.938205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec5fe3455ca9'
down_revision: Union[str, None] = ('c9d8e7f6a5b4', 'd186a0c1e2f3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
