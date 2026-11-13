"""fusion BE-210 et develop

Revision ID: 2402c108f2e6
Revises: be210c0d1e2f, c117e5a1b2d3
Create Date: 2026-11-07 14:16:03.279153

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2402c108f2e6'
down_revision: Union[str, None] = ('be210c0d1e2f', 'c117e5a1b2d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
