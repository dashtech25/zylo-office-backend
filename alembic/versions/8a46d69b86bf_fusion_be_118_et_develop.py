"""fusion BE-118 et develop

Revision ID: 8a46d69b86bf
Revises: a118c0de0118, ec5fe3455ca9
Create Date: 2026-11-06 05:19:03.010459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a46d69b86bf'
down_revision: Union[str, None] = ('a118c0de0118', 'ec5fe3455ca9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
