"""fusion BE-246 et develop

Revision ID: 55b65917a1f4
Revises: 2380bdbe5074, a246c1d2e3f4
Create Date: 2026-11-05 17:49:30.839097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55b65917a1f4'
down_revision: Union[str, None] = ('2380bdbe5074', 'a246c1d2e3f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
