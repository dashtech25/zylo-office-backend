"""agrégat subscription : trois axes d'état indépendants (BE-079)

Revision ID: e079a1b2c3d4
Revises: f668520e8d62
Create Date: 2026-11-04

Migration additive sur la table `subscription` (BE-023, non recréée ici). Elle ajoute
trois colonnes, une par axe de la machine d'état conceptuelle :
- `lifecycleStatus` : cycle de vie (pending, trialing, active, change_scheduled,
  cancel_scheduled, expired, cancelled, close_pending, subscription_closed) ;
- `financialStatus` : état financier (none, pending, settled, failed) ;
- `incidentStatus` : incident de paiement ou de litige (none, past_due, grace,
  suspended, disputed, incomplete).

Les trois axes sont indépendants : aucune colonne ne dérive d'une autre. La colonne
`status` (BE-023) est conservée telle quelle, car les routes de BE-026 et de BE-027
la lisent encore.

Backfill : `lifecycleStatus` reprend `status`, avec `trial` traduit en `trialing`
(libellé de la machine d'état). Les lignes existantes ont `financialStatus` et
`incidentStatus` à `none`, faute d'historique de paiement fiable.

Retour arrière : suppression des contraintes puis des trois colonnes. `status` n'a
jamais été modifié, donc aucune donnée d'origine n'est perdue.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e079a1b2c3d4"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIFECYCLE_VALUES = (
    "pending", "trialing", "active", "change_scheduled", "cancel_scheduled",
    "expired", "cancelled", "close_pending", "subscription_closed",
)
FINANCIAL_VALUES = ("none", "pending", "settled", "failed")
INCIDENT_VALUES = ("none", "past_due", "grace", "suspended", "disputed", "incomplete")


def _liste_sql(valeurs: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valeurs)


def upgrade() -> None:
    op.add_column(
        "subscription",
        sa.Column("lifecycleStatus", sa.String(length=30), nullable=False, server_default="trialing",
                  comment="Axe cycle de vie de l'abonnement (BE-079)."),
    )
    op.add_column(
        "subscription",
        sa.Column("financialStatus", sa.String(length=30), nullable=False, server_default="none",
                  comment="Axe financier de l'abonnement, indépendant du cycle de vie (BE-079)."),
    )
    op.add_column(
        "subscription",
        sa.Column("incidentStatus", sa.String(length=30), nullable=False, server_default="none",
                  comment="Axe incident de l'abonnement, indépendant des deux autres (BE-079)."),
    )
    op.execute(
        "UPDATE subscription SET \"lifecycleStatus\" = "
        "CASE status WHEN 'trial' THEN 'trialing' ELSE status END"
    )
    op.create_check_constraint(
        "ck_subscription_lifecycle_status", "subscription",
        f'"lifecycleStatus" IN ({_liste_sql(LIFECYCLE_VALUES)})',
    )
    op.create_check_constraint(
        "ck_subscription_financial_status", "subscription",
        f'"financialStatus" IN ({_liste_sql(FINANCIAL_VALUES)})',
    )
    op.create_check_constraint(
        "ck_subscription_incident_status", "subscription",
        f'"incidentStatus" IN ({_liste_sql(INCIDENT_VALUES)})',
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscription_incident_status", "subscription", type_="check")
    op.drop_constraint("ck_subscription_financial_status", "subscription", type_="check")
    op.drop_constraint("ck_subscription_lifecycle_status", "subscription", type_="check")
    op.drop_column("subscription", "incidentStatus")
    op.drop_column("subscription", "financialStatus")
    op.drop_column("subscription", "lifecycleStatus")
