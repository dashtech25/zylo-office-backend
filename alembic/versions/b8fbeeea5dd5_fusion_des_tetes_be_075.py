"""Fusion des tetes be-075

Revision ID: b8fbeeea5dd5
Revises: a7c2e4f1b936, e03b52959415
Create Date: 2026-11-04 01:43:45.582299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8fbeeea5dd5'
down_revision: Union[str, None] = ('a7c2e4f1b936', 'e03b52959415')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
