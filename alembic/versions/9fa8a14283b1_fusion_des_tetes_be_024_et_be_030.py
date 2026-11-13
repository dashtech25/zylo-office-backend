"""fusion des tetes BE-024 et BE-030

Revision ID: 9fa8a14283b1
Revises: e5f6a7b8c9d0, eb922c50f9b5
Create Date: 2026-11-03 23:38:05.698095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9fa8a14283b1'
down_revision: Union[str, None] = ('e5f6a7b8c9d0', 'eb922c50f9b5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
