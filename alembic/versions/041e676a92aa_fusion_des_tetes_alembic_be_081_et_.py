"""Fusion des tetes Alembic be-081 et develop

Revision ID: 041e676a92aa
Revises: a81c0c4e0b01, d8eaf380eecb
Create Date: 2026-11-05 04:32:21.662686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '041e676a92aa'
down_revision: Union[str, None] = ('a81c0c4e0b01', 'd8eaf380eecb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
