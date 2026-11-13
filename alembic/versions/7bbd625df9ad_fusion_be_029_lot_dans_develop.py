"""fusion be-029-lot dans develop

Revision ID: 7bbd625df9ad
Revises: 2e1730fcde08, f668520e8d62
Create Date: 2026-11-04 01:09:33.229916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bbd625df9ad'
down_revision: Union[str, None] = ('2e1730fcde08', 'f668520e8d62')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
