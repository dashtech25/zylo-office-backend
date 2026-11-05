"""merge be168 dans develop

Revision ID: c13acdcdccec
Revises: 52789084e923, 8e5a2c1d9f3b
Create Date: 2026-11-05 08:50:03.333553

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c13acdcdccec'
down_revision: Union[str, None] = ('52789084e923', '8e5a2c1d9f3b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
