"""fusion tetes be086 et develop

Revision ID: 32ad63ed64c7
Revises: 041531056547, a086f1n4c7e2
Create Date: 2026-11-04 02:43:08.996528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32ad63ed64c7'
down_revision: Union[str, None] = ('041531056547', 'a086f1n4c7e2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
