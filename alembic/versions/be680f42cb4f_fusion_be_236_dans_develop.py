"""fusion be-236 dans develop

Revision ID: be680f42cb4f
Revises: 4999c84636ac, b236c1a0d001
Create Date: 2026-11-05 09:52:00.755451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be680f42cb4f'
down_revision: Union[str, None] = ('4999c84636ac', 'b236c1a0d001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
