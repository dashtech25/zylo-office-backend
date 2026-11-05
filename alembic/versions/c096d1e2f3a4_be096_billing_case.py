"""BE-096 : table billing_case (cas de facturation et d'assistance)

Revision ID: c096d1e2f3a4
Revises: 2380bdbe5074
Create Date: 2026-11-05

Crée `billing_case` : un cas par ouverture, rattaché à un tenant (`organizationId`, isolation
CA-4). Colonnes prévues par BE-096 (`scope`, `subjectRef`, `status`, `assigneeId`, `reason`,
`openedAt`), plus `resolutionReason` et `resolvedAt`, renseignées à la résolution (CA-2). Les
colonnes sont en camelCase, la table en snake_case (QE-FAC-31). Aucune donnée n'est copiée.

Downgrade : retire les index puis la table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c096d1e2f3a4"
down_revision: Union[str, None] = "2380bdbe5074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_case",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False,
                  comment="Identifiant du cas."),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False,
                  comment="Tenant propriétaire du cas (isolation, CA-4)."),
        sa.Column("scope", sa.String(length=20), nullable=False,
                  comment="Périmètre du cas (tenant ou payeur)."),
        sa.Column("subjectRef", sa.String(length=255), nullable=False,
                  comment="Référence de l'objet concerné par le cas."),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open",
                  comment="Statut du cas (BE-096)."),
        sa.Column("assigneeId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True,
                  comment="Personne à qui le cas est assigné, s'il l'est."),
        sa.Column("reason", sa.Text(), nullable=False,
                  comment="Motif d'ouverture du cas."),
        sa.Column("openedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
                  comment="Heure d'ouverture du cas."),
        sa.Column("resolutionReason", sa.Text(), nullable=True,
                  comment="Motif de résolution, NULL tant que le cas n'est pas résolu."),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True,
                  comment="Heure de résolution, NULL tant que le cas n'est pas résolu."),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'investigating', 'action_pending', 'resolved', 'closed', 'escalated')",
            name="ck_billing_case_status",
        ),
        comment="Cas de facturation ou d'assistance rattaché à un tenant (BE-096).",
    )
    op.create_index("ix_billing_case_organizationId", "billing_case", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_billing_case_organizationId", table_name="billing_case")
    op.drop_table("billing_case")
