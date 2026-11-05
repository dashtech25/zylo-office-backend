"""fusion be-128 et be-125

Revision ID: 9230d532caa6
Revises: 495a7fcdc066, d125a0ce0125
Create Date: 2026-11-05 06:43:58.209646

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9230d532caa6'
down_revision: Union[str, None] = ('495a7fcdc066', 'd125a0ce0125')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
