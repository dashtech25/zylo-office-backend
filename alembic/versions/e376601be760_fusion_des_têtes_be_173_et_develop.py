"""fusion des têtes be-173 et develop

Revision ID: e376601be760
Revises: 84a2fbf33cc8, a7c3e91b2f54
Create Date: 2026-11-05 06:50:49.581956

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e376601be760'
down_revision: Union[str, None] = ('84a2fbf33cc8', 'a7c3e91b2f54')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
