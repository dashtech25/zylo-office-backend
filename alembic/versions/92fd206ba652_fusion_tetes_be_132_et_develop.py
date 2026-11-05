"""fusion tetes be-132 et develop

Revision ID: 92fd206ba652
Revises: 9afedaef1361, b132d1a60132
Create Date: 2026-11-05 05:50:23.271130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92fd206ba652'
down_revision: Union[str, None] = ('9afedaef1361', 'b132d1a60132')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
