"""fusion BE-185 et develop

Revision ID: 0565670f6369
Revises: 54ba4aaf7237, b185c0d1e2f3
Create Date: 2026-11-05 18:39:24.149210

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0565670f6369'
down_revision: Union[str, None] = ('54ba4aaf7237', 'b185c0d1e2f3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
