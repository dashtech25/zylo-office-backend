"""fusion BE-238 et develop

Revision ID: adce56acf5ff
Revises: 089d4c7e2a10, b238d1e2f3a4
Create Date: 2026-11-05 17:14:51.887747

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'adce56acf5ff'
down_revision: Union[str, None] = ('089d4c7e2a10', 'b238d1e2f3a4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
