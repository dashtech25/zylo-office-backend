"""fusion des têtes be-167 et develop

Revision ID: 84a2fbf33cc8
Revises: 7c3e9d2b4a10, cdcca54d221c
Create Date: 2026-11-05 06:49:58.497883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84a2fbf33cc8'
down_revision: Union[str, None] = ('7c3e9d2b4a10', 'cdcca54d221c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
