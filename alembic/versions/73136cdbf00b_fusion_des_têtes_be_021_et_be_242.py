"""fusion des têtes be-021 et be-242

Revision ID: 73136cdbf00b
Revises: b60e229ba2de, fa35dace3fea
Create Date: 2026-11-03 22:53:51.812276

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73136cdbf00b'
down_revision: Union[str, None] = ('b60e229ba2de', 'fa35dace3fea')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
