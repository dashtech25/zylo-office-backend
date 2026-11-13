"""fusion be-049-lot dans develop

Revision ID: 37c874aed5ed
Revises: 3a2990daf8ef, be049a1b2c3d
Create Date: 2026-11-05 05:17:20.964810

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37c874aed5ed'
down_revision: Union[str, None] = ('3a2990daf8ef', 'be049a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
