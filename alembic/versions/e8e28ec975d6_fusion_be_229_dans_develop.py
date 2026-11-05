"""fusion be-229 dans develop

Revision ID: e8e28ec975d6
Revises: b229a0c0d229, b313a4dc1718
Create Date: 2026-11-05 09:44:00.547379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8e28ec975d6'
down_revision: Union[str, None] = ('b229a0c0d229', 'b313a4dc1718')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
