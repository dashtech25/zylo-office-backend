"""fusion tetes be088 et develop

Revision ID: d5624b3c990f
Revises: 32ad63ed64c7, b088c0d1e2f3
Create Date: 2026-11-04 02:45:12.984858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5624b3c990f'
down_revision: Union[str, None] = ('32ad63ed64c7', 'b088c0d1e2f3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
