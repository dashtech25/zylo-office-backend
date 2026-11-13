"""fusion tetes be-093 et develop

Revision ID: 9afedaef1361
Revises: 6d8693f9201f, e093a7b1c2d4
Create Date: 2026-11-05 05:47:21.393415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9afedaef1361'
down_revision: Union[str, None] = ('6d8693f9201f', 'e093a7b1c2d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
