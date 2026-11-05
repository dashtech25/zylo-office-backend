"""fusion be-146-lot dans develop

Revision ID: 12a5bb79f642
Revises: 37c874aed5ed, b146c0de0146
Create Date: 2026-11-05 05:20:38.191368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12a5bb79f642'
down_revision: Union[str, None] = ('37c874aed5ed', 'b146c0de0146')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
