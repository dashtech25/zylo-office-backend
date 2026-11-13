"""fusion tetes be085 et be262

Revision ID: 085f6bf39c20
Revises: c085e4f1a2b3, f6bf39c21bf7
Create Date: 2026-11-05 18:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes
(BE-085 synchronisation des droits et tête issue de BE-095/BE-262).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '085f6bf39c20'
down_revision: Union[str, None] = ('c085e4f1a2b3', 'f6bf39c21bf7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
