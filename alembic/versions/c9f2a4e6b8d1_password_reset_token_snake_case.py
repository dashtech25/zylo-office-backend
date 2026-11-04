"""Renomme la table des jetons de récupération en snake_case (BE-019).

Décision du propriétaire : le nom de table devient `password_reset_token`.
Seul le nom de table change ; colonnes, index et contraintes conservent leurs
noms, ce qui évite de toucher les requêtes et l'index partiel d'unicité.

Revision ID: c9f2a4e6b8d1
Revises: 82b12c50c3f6
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c9f2a4e6b8d1"
down_revision: Union[str, None] = "82b12c50c3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Renomme `passwordResetToken` en `password_reset_token` (données conservées)."""
    op.rename_table("passwordResetToken", "password_reset_token")


def downgrade() -> None:
    """Rétablit le nom camelCase `passwordResetToken` (données conservées)."""
    op.rename_table("password_reset_token", "passwordResetToken")
