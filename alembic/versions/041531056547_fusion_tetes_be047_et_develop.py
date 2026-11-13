"""fusion tetes be047 et develop

Revision ID: 041531056547
Revises: 33e0d390444b, be047c1d2e3f
Create Date: 2026-11-04 02:39:53.626393

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '041531056547'
down_revision: Union[str, None] = ('33e0d390444b', 'be047c1d2e3f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
