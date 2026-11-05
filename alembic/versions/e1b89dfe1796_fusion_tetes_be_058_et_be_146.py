"""fusion tetes be-058 et be-146

Revision ID: e1b89dfe1796
Revises: 058b1c2d3e4f, 12a5bb79f642
Create Date: 2026-11-05 05:42:11.290356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1b89dfe1796'
down_revision: Union[str, None] = ('058b1c2d3e4f', '12a5bb79f642')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
