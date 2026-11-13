"""Fusion des cinq tetes de develop apres reconciliation BE-195 196 198 201 203 204 209 214

Revision ID: f48007065e5d
Revises: 3b4b9d72e6b8, 9ecfcd17858f, a195c0de0195, be196_add_columns, be214001
Create Date: 2026-11-13 03:32:42.172949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f48007065e5d'
down_revision: Union[str, None] = ('3b4b9d72e6b8', '9ecfcd17858f', 'a195c0de0195', 'be196_add_columns', 'be214001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
