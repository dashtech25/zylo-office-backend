"""changement de plan : table plan_change (BE-088)

Revision ID: b088c0d1e2f3
Revises: 12b9bd0b8c15
Create Date: 2026-11-04

Crée la table `plan_change` (app/billing/models.py::PlanChange) : demandes de
changement de plan d'un abonnement, appliquées à échéance (BE-088).

Contraintes :
- `subscriptionId` -> `subscription.id` et `targetPlanVersionSnapshotId` ->
  `plan_version_snapshot.id` (FK explicites, QE-FAC-04) ;
- `direction` limitée à `upgrade` ou `downgrade` (CHECK) ;
- index unique partiel `uq_plan_change_scheduled_par_abonnement` sur `subscriptionId`
  où `status = 'scheduled'` : au plus une demande planifiée par abonnement, garantie
  par la base et pas seulement par le service.

Aucune donnée n'est insérée. Retour arrière : suppression de la table, qui supprime
ses index et contraintes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b088c0d1e2f3"
down_revision: Union[str, None] = "12b9bd0b8c15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_change",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscriptionId", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscription.id"),
                  nullable=False, comment="Abonnement concerné."),
        sa.Column("targetPlanVersionSnapshotId", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("plan_version_snapshot.id"), nullable=False,
                  comment="Instantané figé de la version d'offre cible (BE-075)."),
        sa.Column("direction", sa.String(length=20), nullable=False,
                  comment="upgrade ou downgrade (BE-088)."),
        sa.Column("effectiveAt", sa.DateTime(timezone=True), nullable=False,
                  comment="Date d'effet du changement (échéance pour un downgrade)."),
        sa.Column("status", sa.String(length=30), nullable=False,
                  comment="Statut de la demande : scheduled (BE-088)."),
        sa.Column("previewJson", postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment="Aperçu présenté au moment de la demande (BE-088)."),
        comment="Demande de changement de plan d'un abonnement, appliquée à échéance (BE-088).",
    )
    op.create_index("ix_plan_change_subscriptionId", "plan_change", ["subscriptionId"])
    op.create_index("ix_plan_change_targetPlanVersionSnapshotId", "plan_change", ["targetPlanVersionSnapshotId"])
    op.create_check_constraint(
        "ck_plan_change_direction", "plan_change", "direction IN ('upgrade', 'downgrade')",
    )
    op.create_index(
        "uq_plan_change_scheduled_par_abonnement", "plan_change", ["subscriptionId"],
        unique=True, postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_change_scheduled_par_abonnement", table_name="plan_change")
    op.drop_constraint("ck_plan_change_direction", "plan_change", type_="check")
    op.drop_index("ix_plan_change_targetPlanVersionSnapshotId", table_name="plan_change")
    op.drop_index("ix_plan_change_subscriptionId", table_name="plan_change")
    op.drop_table("plan_change")
