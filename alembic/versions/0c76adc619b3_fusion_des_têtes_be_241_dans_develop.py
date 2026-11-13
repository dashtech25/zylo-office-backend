"""fusion des têtes be-241 dans develop

Revision ID: 0c76adc619b3
Revises: d51b3bc6fe0c, db7ff2e5c60e
Create Date: 2026-11-04 02:27:12.060966

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c76adc619b3'
down_revision: Union[str, None] = ('d51b3bc6fe0c', 'db7ff2e5c60e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
