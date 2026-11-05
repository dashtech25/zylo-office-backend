"""fusion des tetes be-234 dans develop

Revision ID: f32497e0328e
Revises: 1d0dcfadf009, b234a0d1e2f3
Create Date: 2026-11-05 06:59:36.648961

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f32497e0328e'
down_revision: Union[str, None] = ('1d0dcfadf009', 'b234a0d1e2f3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
