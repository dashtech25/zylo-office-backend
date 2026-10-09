"""merge unicité de l'e-mail sans casse (T-013) et abonnements Web Push (T-004b lot 2)

Revision ID: 7c2e9a1f4b8d
Revises: c5a1d9e3f7b2, f3a4b5c6d7e8
Create Date: 2026-10-09

Intention : deux branches de schéma partaient de 5b1c9e7d3a4f (T-013 : index
unique sur lower(email) ; T-004b lot 2 : table notificationPushSubscription).
Cette migration de fusion ne modifie aucune donnée ni aucun schéma : elle
rétablit une seule tête alembic.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '7c2e9a1f4b8d'
down_revision: Union[str, None] = ('c5a1d9e3f7b2', 'f3a4b5c6d7e8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
