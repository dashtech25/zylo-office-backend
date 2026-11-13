"""Fusion des tetes BE-045 et BE-071

Revision ID: dcca8a653959
Revises: 7088b9c36bc8, e1f2a3b4c5d6
Create Date: 2026-11-04 01:02:30.700909

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcca8a653959'
down_revision: Union[str, None] = ('7088b9c36bc8', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
