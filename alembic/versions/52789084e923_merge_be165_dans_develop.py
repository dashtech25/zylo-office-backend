"""merge be165 dans develop

Revision ID: 52789084e923
Revises: 9dc1e3363030, c165a0b1d2e3
Create Date: 2026-11-05 08:48:22.652954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52789084e923'
down_revision: Union[str, None] = ('9dc1e3363030', 'c165a0b1d2e3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
