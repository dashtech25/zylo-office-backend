"""fusion be-040 et tete existante

Revision ID: 9a075a4572eb
Revises: 82522140e368, b040c4a10e01
Create Date: 2026-11-03 23:10:56.372800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a075a4572eb'
down_revision: Union[str, None] = ('82522140e368', 'b040c4a10e01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
