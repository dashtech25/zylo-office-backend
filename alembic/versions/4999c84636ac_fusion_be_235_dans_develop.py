"""fusion be-235 dans develop

Revision ID: 4999c84636ac
Revises: d235a0b1c2d3, e8e28ec975d6
Create Date: 2026-11-05 09:49:26.843986

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4999c84636ac'
down_revision: Union[str, None] = ('d235a0b1c2d3', 'e8e28ec975d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
