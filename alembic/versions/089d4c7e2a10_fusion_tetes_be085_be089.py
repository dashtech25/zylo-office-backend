"""fusion tetes be085 et be089

Revision ID: 089d4c7e2a10
Revises: 085f6bf39c20, c4089b2a1e7f
Create Date: 2026-11-05 19:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes
(BE-085 synchronisation des droits et BE-089 renouvellement d'abonnement).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '089d4c7e2a10'
down_revision: Union[str, None] = ('085f6bf39c20', 'c4089b2a1e7f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
