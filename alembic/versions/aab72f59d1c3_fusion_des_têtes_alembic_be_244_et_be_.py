"""Fusion des têtes Alembic be-244 et be-237 dans develop

Revision ID: aab72f59d1c3
Revises: 7c0052761f05, b244a1c2d3e4
Create Date: 2026-11-05 10:01:47.819049

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aab72f59d1c3'
down_revision: Union[str, None] = ('7c0052761f05', 'b244a1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
