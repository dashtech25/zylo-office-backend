"""Fusion des tetes Alembic be-087 et develop

Revision ID: 881bfa754423
Revises: 041e676a92aa, b087c1d2e3f4
Create Date: 2026-11-05 04:35:07.219227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '881bfa754423'
down_revision: Union[str, None] = ('041e676a92aa', 'b087c1d2e3f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
