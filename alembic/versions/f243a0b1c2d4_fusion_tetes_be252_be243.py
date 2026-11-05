"""fusion tetes be252 et be243

Revision ID: f243a0b1c2d4
Revises: a243b0c1d2e3, e252d0a1f7c3
Create Date: 2026-11-05 21:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes
(develop après BE-252 compensations, et BE-243 export de données par sujet ou tenant).
Downgrade sans effet : chaque branche est réversible par sa propre migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f243a0b1c2d4'
down_revision: Union[str, None] = ('a243b0c1d2e3', 'e252d0a1f7c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
