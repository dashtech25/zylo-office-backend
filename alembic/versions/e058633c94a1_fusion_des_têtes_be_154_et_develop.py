"""fusion des têtes be-154 et develop

Revision ID: e058633c94a1
Revises: 702914c4df91, a3c9e1f20b76
Create Date: 2026-11-05 06:04:04.512740

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e058633c94a1'
down_revision: Union[str, None] = ('702914c4df91', 'a3c9e1f20b76')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
