"""fusion des têtes be-231 dans develop

Revision ID: db7ff2e5c60e
Revises: 12b9bd0b8c15, be231a1b2c3d
Create Date: 2026-11-04 02:25:59.082599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db7ff2e5c60e'
down_revision: Union[str, None] = ('12b9bd0b8c15', 'be231a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
