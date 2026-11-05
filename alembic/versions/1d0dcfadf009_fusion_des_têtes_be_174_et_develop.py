"""fusion des têtes be-174 et develop

Revision ID: 1d0dcfadf009
Revises: 174a0b1c2d3e, e376601be760
Create Date: 2026-11-05 06:53:40.182515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d0dcfadf009'
down_revision: Union[str, None] = ('174a0b1c2d3e', 'e376601be760')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
