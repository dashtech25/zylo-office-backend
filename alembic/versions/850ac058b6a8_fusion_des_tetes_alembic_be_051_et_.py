"""Fusion des tetes Alembic be-051 et develop

Revision ID: 850ac058b6a8
Revises: 2dcc3b17657c, be051d2e3f4a
Create Date: 2026-11-05 04:26:42.753330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '850ac058b6a8'
down_revision: Union[str, None] = ('2dcc3b17657c', 'be051d2e3f4a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
