"""fusion be152 be191 heads

Revision ID: 2dcc3b17657c
Revises: 254220e168b5, f2a8c1d7e903
Create Date: 2026-11-05 03:50:09.284463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2dcc3b17657c'
down_revision: Union[str, None] = ('254220e168b5', 'f2a8c1d7e903')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
