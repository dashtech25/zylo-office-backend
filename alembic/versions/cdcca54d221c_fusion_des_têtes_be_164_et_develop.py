"""fusion des têtes be-164 et develop

Revision ID: cdcca54d221c
Revises: 9230d532caa6, 9b164a0c164e
Create Date: 2026-11-05 06:47:39.274409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdcca54d221c'
down_revision: Union[str, None] = ('9230d532caa6', '9b164a0c164e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
