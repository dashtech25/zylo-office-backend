"""fusion tetes be262 et be095

Revision ID: f6bf39c21bf7
Revises: 8673695c5fb4, a262c0de1a7e
Create Date: 2026-11-05 17:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes (BE-095 et BE-262).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6bf39c21bf7'
down_revision: Union[str, None] = ('8673695c5fb4', 'a262c0de1a7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
