"""fusion des têtes be-166 et develop

Revision ID: 702914c4df91
Revises: 92fd206ba652, c166e0f1a2b3
Create Date: 2026-11-05 06:01:45.163085

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '702914c4df91'
down_revision: Union[str, None] = ('92fd206ba652', 'c166e0f1a2b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
