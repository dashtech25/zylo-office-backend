"""fusion des tetes BE-019 et BE-024

Revision ID: eb922c50f9b5
Revises: b024e7a1c5d3, c9f2a4e6b8d1
Create Date: 2026-11-03 23:37:06.801858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb922c50f9b5'
down_revision: Union[str, None] = ('b024e7a1c5d3', 'c9f2a4e6b8d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
