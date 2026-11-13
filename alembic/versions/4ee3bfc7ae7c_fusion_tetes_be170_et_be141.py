"""fusion tetes be170 et be141

Revision ID: 4ee3bfc7ae7c
Revises: c4d8e1f2a903, fd57ba293e8b
Create Date: 2026-11-05 10:31:44.608386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ee3bfc7ae7c'
down_revision: Union[str, None] = ('c4d8e1f2a903', 'fd57ba293e8b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
