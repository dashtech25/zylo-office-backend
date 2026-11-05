"""Fusion des tetes Alembic be-098 et develop

Revision ID: d8eaf380eecb
Revises: 850ac058b6a8, b098e0f1a2c3
Create Date: 2026-11-05 04:29:43.856351

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8eaf380eecb'
down_revision: Union[str, None] = ('850ac058b6a8', 'b098e0f1a2c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
