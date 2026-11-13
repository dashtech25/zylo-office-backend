"""fusion be007 dans develop

Revision ID: 82522140e368
Revises: 73136cdbf00b, b8e3f1a20c47
Create Date: 2026-11-03 22:58:36.389840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82522140e368'
down_revision: Union[str, None] = ('73136cdbf00b', 'b8e3f1a20c47')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
