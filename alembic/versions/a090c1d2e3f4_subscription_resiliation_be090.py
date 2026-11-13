"""resiliation d'abonnement : mode et date d'effet (BE-090)

Revision ID: a090c1d2e3f4
Revises: 169de7fb56af
Create Date: 2026-11-04

Migration additive sur la table `subscription` (BE-023, non recréée ici). Elle ajoute
deux colonnes nullables, renseignées par la résiliation (app/billing/cancellation) :
- `cancelMode` : `end_of_period` (à échéance, mode par défaut) ou `immediate` (réservé :
  refusé par le service tant que QE-FAC-08 n'est pas tranché, mais la valeur est prévue
  par la contrainte pour ne pas refaire de migration le jour où il l'est) ;
- `cancelEffectiveAt` : date d'effet de la résiliation.

Les lignes existantes restent à NULL : aucune résiliation n'a été demandée.

Retour arrière : suppression de la contrainte puis des deux colonnes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a090c1d2e3f4"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription",
        sa.Column("cancelMode", sa.String(length=20), nullable=True,
                  comment="Mode de résiliation : end_of_period ou immediate (BE-090)."),
    )
    op.add_column(
        "subscription",
        sa.Column("cancelEffectiveAt", sa.DateTime(timezone=True), nullable=True,
                  comment="Date d'effet de la résiliation (BE-090)."),
    )
    op.create_check_constraint(
        "ck_subscription_cancel_mode", "subscription",
        "\"cancelMode\" IS NULL OR \"cancelMode\" IN ('end_of_period', 'immediate')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscription_cancel_mode", "subscription", type_="check")
    op.drop_column("subscription", "cancelEffectiveAt")
    op.drop_column("subscription", "cancelMode")
