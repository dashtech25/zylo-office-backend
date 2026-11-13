"""fusion tetes be089 et be252

Revision ID: e252d0a1f7c3
Revises: 089d4c7e2a10, b252c3d4e5f6
Create Date: 2026-11-05 20:00:00.000000

Migration de fusion sans changement de schéma : réconcilie les deux têtes
(develop après BE-089 renouvellement d'abonnement, et BE-252 compensations).
Downgrade sans effet : la table compensations est supprimée par le downgrade de BE-252.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e252d0a1f7c3'
down_revision: Union[str, None] = ('089d4c7e2a10', 'b252c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
