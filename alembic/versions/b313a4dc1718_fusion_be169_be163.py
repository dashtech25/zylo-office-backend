"""fusion be169 be163

Revision ID: b313a4dc1718
Revises: 3c9e0b7f2a14, 9a4f1c6d2e75
Create Date: 2026-11-05 09:41:42.246447

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b313a4dc1718'
down_revision: Union[str, None] = ('3c9e0b7f2a14', '9a4f1c6d2e75')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
