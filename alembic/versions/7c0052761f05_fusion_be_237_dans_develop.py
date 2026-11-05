"""fusion be-237 dans develop

Revision ID: 7c0052761f05
Revises: a237b1c0d9e8, be680f42cb4f
Create Date: 2026-11-05 09:53:37.502615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c0052761f05'
down_revision: Union[str, None] = ('a237b1c0d9e8', 'be680f42cb4f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
