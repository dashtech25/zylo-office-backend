"""fusion BE-182 et develop

Revision ID: 52e99f1b21b5
Revises: 09fc9f704065, c1e8be182a01
Create Date: 2026-11-05 18:02:42.193751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52e99f1b21b5'
down_revision: Union[str, None] = ('09fc9f704065', 'c1e8be182a01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
