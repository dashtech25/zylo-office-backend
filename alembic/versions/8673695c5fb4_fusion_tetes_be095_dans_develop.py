"""fusion tetes be095 dans develop

Revision ID: 8673695c5fb4
Revises: a2456e1f2b3c, c095a1b2d3e4
Create Date: 2026-11-05 16:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes (develop et BE-095).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8673695c5fb4'
down_revision: Union[str, None] = ('a2456e1f2b3c', 'c095a1b2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
