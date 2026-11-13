"""fusion des têtes be-242 et be-004

Revision ID: fa35dace3fea
Revises: c7ecfe8a11be, f0e1d2c3b4a5
Create Date: 2026-11-03 22:52:20.766029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa35dace3fea'
down_revision: Union[str, None] = ('c7ecfe8a11be', 'f0e1d2c3b4a5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
