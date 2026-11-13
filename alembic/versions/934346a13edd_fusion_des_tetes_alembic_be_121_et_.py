"""Fusion des tetes Alembic be-121 et develop

Revision ID: 934346a13edd
Revises: 881bfa754423, a121c0de0121
Create Date: 2026-11-05 04:38:06.777773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '934346a13edd'
down_revision: Union[str, None] = ('881bfa754423', 'a121c0de0121')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
