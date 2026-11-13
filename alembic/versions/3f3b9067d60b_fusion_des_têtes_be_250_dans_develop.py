"""fusion des têtes be-250 dans develop

Revision ID: 3f3b9067d60b
Revises: 0c76adc619b3, a250b1c2d3e4
Create Date: 2026-11-04 02:28:29.956682

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f3b9067d60b'
down_revision: Union[str, None] = ('0c76adc619b3', 'a250b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
