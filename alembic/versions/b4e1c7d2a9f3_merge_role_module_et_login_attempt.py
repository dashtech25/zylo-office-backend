"""merge role.moduleCode (T-018) et loginAttempt (T-012)

Revision ID: b4e1c7d2a9f3
Revises: a7d3c1e9f024, a9b8c7d6e5f4
Create Date: 2026-10-09

Intention : deux branches de schéma partaient de e2f3a4b5c6d7 (T-018 : colonne
role.moduleCode ; T-012 : table loginAttempt). Cette migration de fusion ne
modifie aucune donnée ni aucun schéma : elle rétablit une seule tête alembic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e1c7d2a9f3'
down_revision: Union[str, None] = ('a7d3c1e9f024', 'a9b8c7d6e5f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
