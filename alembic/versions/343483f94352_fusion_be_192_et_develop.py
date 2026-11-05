"""fusion BE-192 et develop

Revision ID: 343483f94352
Revises: b187e0a1c2d3, d192a0b1c2e3
Create Date: 2026-11-05 18:21:49.159382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '343483f94352'
down_revision: Union[str, None] = ('b187e0a1c2d3', 'd192a0b1c2e3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
