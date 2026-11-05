"""fusion des têtes be-160 et develop

Revision ID: 5e31981cf46c
Revises: 5f1e2a3b4c6d, e058633c94a1
Create Date: 2026-11-05 06:06:13.606439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e31981cf46c'
down_revision: Union[str, None] = ('5f1e2a3b4c6d', 'e058633c94a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
