"""fusion BE-096 et develop

Revision ID: 09fc9f704065
Revises: 55b65917a1f4, c096d1e2f3a4
Create Date: 2026-11-05 17:58:43.459497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09fc9f704065'
down_revision: Union[str, None] = ('55b65917a1f4', 'c096d1e2f3a4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
