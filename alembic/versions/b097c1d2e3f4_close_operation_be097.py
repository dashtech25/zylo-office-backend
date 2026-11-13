"""clôture d'abonnement : table close_operation (BE-097)

Revision ID: b097c1d2e3f4
Revises: f243a0b1c2d4
Create Date: 2026-11-05

Crée la table `close_operation` : une ligne par clôture d'abonnement. Les colonnes
suivent la fiche BE-097 (`id`, `subscriptionId`, `status`, `prerequisitesJson`,
`requestedAt`). Le statut est contraint par CHECK ; la table ne touche à aucune autre.

Retour arrière : suppression de la table (ses lignes sont perdues).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b097c1d2e3f4"
down_revision: Union[str, None] = "f243a0b1c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "close_operation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscriptionId", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscription.id"), nullable=False,
                  comment="Abonnement clôturé."),
        sa.Column("status", sa.String(length=40), nullable=False, comment="Statut de la clôture (BE-097)."),
        sa.Column("prerequisitesJson", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb"),
                  comment="Résultat vérifié de chaque prérequis (BE-097)."),
        sa.Column("requestedAt", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
                  comment="Heure de la demande de clôture."),
        sa.CheckConstraint(
            "status IN ('requested', 'close_pending_finance', 'close_pending_entitlement', "
            "'close_pending_data', 'completed', 'blocked', 'escalated')",
            name="ck_close_operation_status",
        ),
        comment="Clôture d'un abonnement, prérequis vérifiés un à un (BE-097).",
    )
    op.create_index("ix_close_operation_subscriptionId", "close_operation", ["subscriptionId"])


def downgrade() -> None:
    op.drop_index("ix_close_operation_subscriptionId", table_name="close_operation")
    op.drop_table("close_operation")
