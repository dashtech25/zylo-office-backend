"""fusion BE-091 et develop

Revision ID: fb5bcc482678
Revises: c238f2430a1b, e091a1b2c3d4
Create Date: 2026-11-05 17:31:30.998826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb5bcc482678'
down_revision: Union[str, None] = ('c238f2430a1b', 'e091a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
