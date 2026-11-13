"""fusion BE-097 et develop

Revision ID: 2380bdbe5074
Revises: b097c1d2e3f4, fb5bcc482678
Create Date: 2026-11-05 17:33:49.462474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2380bdbe5074'
down_revision: Union[str, None] = ('b097c1d2e3f4', 'fb5bcc482678')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
