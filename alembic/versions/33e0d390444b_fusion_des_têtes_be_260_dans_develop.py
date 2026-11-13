"""fusion des têtes be-260 dans develop

Revision ID: 33e0d390444b
Revises: 3f3b9067d60b, c3a9e1f07b52
Create Date: 2026-11-04 02:29:46.027951

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33e0d390444b'
down_revision: Union[str, None] = ('3f3b9067d60b', 'c3a9e1f07b52')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
