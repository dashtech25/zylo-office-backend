"""(empty - duplicates 0001be196001)

Revision ID: be196_add_columns
Revises: 0001be196001
Create Date: 2026-11-12 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'be196_add_columns'
down_revision: Union[str, Sequence[str], None] = '0001be196001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Empty migration - columns already added by 0001be196001
    pass


def downgrade() -> None:
    # Empty migration - no changes to reverse
    pass
