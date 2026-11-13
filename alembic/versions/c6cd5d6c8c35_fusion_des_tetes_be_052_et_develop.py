"""Fusion des tetes be-052 et develop

Revision ID: c6cd5d6c8c35
Revises: b052c4e7a1f3, d5624b3c990f
Create Date: 2026-11-05 03:42:10.769542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6cd5d6c8c35'
down_revision: Union[str, None] = ('b052c4e7a1f3', 'd5624b3c990f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
