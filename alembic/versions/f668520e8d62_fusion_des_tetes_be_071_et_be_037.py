"""Fusion des tetes BE-071 et BE-037

Revision ID: f668520e8d62
Revises: dcca8a653959, f5a6b7c8d9e0
Create Date: 2026-11-04 01:03:35.919250

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f668520e8d62'
down_revision: Union[str, None] = ('dcca8a653959', 'f5a6b7c8d9e0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
