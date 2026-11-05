"""merge be-138 et be-144 heads

Revision ID: 9dc1e3363030
Revises: 7b3cdbc1efc8, e144a0de0144
Create Date: 2026-11-05 08:43:18.832762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9dc1e3363030'
down_revision: Union[str, None] = ('7b3cdbc1efc8', 'e144a0de0144')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
