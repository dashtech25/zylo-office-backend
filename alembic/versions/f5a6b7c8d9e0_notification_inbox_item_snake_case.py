"""Renomme la table de l'inbox de notifications en snake_case (BE-037).

Décision du propriétaire : le nom de table devient `notification_inbox_item`,
comme `password_reset_token` (BE-019, révision c9f2a4e6b8d1). Seul le nom de
table change, données comprises. Les index et contraintes conservent leurs
noms (`ix_notificationInboxItem_*`, `uq_notificationInboxItem_event_recipient`) :
le producteur d'idempotence `on_conflict_do_nothing(constraint=...)` et les
index partiels ne sont donc pas touchés.

Revision ID: f5a6b7c8d9e0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Renomme `notificationInboxItem` en `notification_inbox_item` (données conservées)."""
    op.rename_table("notificationInboxItem", "notification_inbox_item")


def downgrade() -> None:
    """Rétablit le nom camelCase `notificationInboxItem` (données conservées)."""
    op.rename_table("notification_inbox_item", "notificationInboxItem")
