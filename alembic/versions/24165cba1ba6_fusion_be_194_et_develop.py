"""fusion BE-194 et develop

Revision ID: 24165cba1ba6
Revises: 02a46cdda276, e194b1d2c3a4
Create Date: 2026-11-06 06:22:12.380155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24165cba1ba6'
down_revision: Union[str, None] = ('02a46cdda276', 'e194b1d2c3a4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
