"""merge be135 dans develop

Revision ID: 290f30a9bcbf
Revises: c13acdcdccec, e135a0ce0135
Create Date: 2026-11-05 08:59:47.781311

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '290f30a9bcbf'
down_revision: Union[str, None] = ('c13acdcdccec', 'e135a0ce0135')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
