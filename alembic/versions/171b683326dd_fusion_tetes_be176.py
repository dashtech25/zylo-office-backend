"""fusion tetes be176

Revision ID: 171b683326dd
Revises: 4ee3bfc7ae7c, c176a0e1b2d3
Create Date: 2026-11-05 10:33:44.097140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '171b683326dd'
down_revision: Union[str, None] = ('4ee3bfc7ae7c', 'c176a0e1b2d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
