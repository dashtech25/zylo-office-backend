"""fusion be204001 et be215a1b2c3d

Revision ID: 3b4b9d72e6b8
Revises: be204001, be215a1b2c3d
Create Date: 2026-11-12 17:44:27.649963

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b4b9d72e6b8'
down_revision: Union[str, None] = ('be204001', 'be215a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
