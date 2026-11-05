"""Charge utile des commandes opérateur d'entitlement (BE-135).

Ajoute `admin_command.payload` (JSONB, nul par défaut). Une commande d'entitlement
doit porter le module visé et l'opération demandée ; le modèle BE-124 n'avait pas de
champ pour cela. Les commandes existantes gardent `payload` à NULL.

Downgrade : la colonne est supprimée, ce qui perd les charges utiles des commandes
d'entitlement déjà créées. Ne pas rétrograder en production sans sauvegarde.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e135a0ce0135"
down_revision: Union[str, None] = "7b3cdbc1efc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_command",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_command", "payload")
