"""fusion BE-100 et develop

Revision ID: 54ba4aaf7237
Revises: be100a0b1c2d, e193c0a1b2d3
Create Date: 2026-11-05 18:36:10.269860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54ba4aaf7237'
down_revision: Union[str, None] = ('be100a0b1c2d', 'e193c0a1b2d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
