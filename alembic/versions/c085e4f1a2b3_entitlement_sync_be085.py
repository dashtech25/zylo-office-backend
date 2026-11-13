"""synchronisation des droits : table entitlement_sync (BE-085)

Revision ID: c085e4f1a2b3
Revises: a2456e1f2b3c
Create Date: 2026-11-05

Crée la table `entitlement_sync` (app/billing/models.py::EntitlementSync) : suivi des
demandes de synchronisation des droits d'un abonnement vers PH-09 (BE-085).

Contraintes :
- `subscriptionId` -> `subscription.id` (FK explicite) et index ;
- `status` limité à requested, applied, failed ou retry_pending (CHECK).

Aucune donnée n'est insérée. Retour arrière : suppression de la table, qui supprime
ses index et contraintes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c085e4f1a2b3"
down_revision: Union[str, None] = "a2456e1f2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entitlement_sync",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscriptionId", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscription.id"),
                  nullable=False, comment="Abonnement dont les droits doivent être synchronisés."),
        sa.Column("status", sa.String(length=30), nullable=False,
                  comment="Statut : requested, applied, failed ou retry_pending (BE-085)."),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0",
                  comment="Nombre d'issues enregistrées (BE-085)."),
        sa.Column("lastErrorCode", sa.String(length=60), nullable=True,
                  comment="Dernier code d'erreur de synchronisation, nul si applied (BE-085)."),
        sa.Column("requestedAt", sa.DateTime(timezone=True), nullable=False,
                  comment="Date de la demande de synchronisation (BE-085)."),
        comment="Suivi d'une demande de synchronisation des droits d'un abonnement (BE-085).",
    )
    op.create_index("ix_entitlement_sync_subscriptionId", "entitlement_sync", ["subscriptionId"])
    op.create_check_constraint(
        "ck_entitlement_sync_status", "entitlement_sync",
        "status IN ('requested', 'applied', 'failed', 'retry_pending')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_entitlement_sync_status", "entitlement_sync", type_="check")
    op.drop_index("ix_entitlement_sync_subscriptionId", table_name="entitlement_sync")
    op.drop_table("entitlement_sync")
