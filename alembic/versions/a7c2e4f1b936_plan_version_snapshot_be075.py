"""instantanés de version d'offre au devis et au contrat : table plan_version_snapshot (BE-075)

Revision ID: a7c2e4f1b936
Revises: f668520e8d62
Create Date: 2026-11-04

Migration additive. Crée la table `plan_version_snapshot` (nom en snake_case,
décision du propriétaire) : id, planRef, planVersion, capturedAt,
sourceCatalogueRef, snapshotJson, plus organizationId pour l'isolation tenant
(CA-4 de BE-075). Aucune donnée existante n'est modifiée.

Retour arrière : suppression de l'index puis de la table. Les instantanés déjà
capturés sont perdus au retour arrière ; ils ne sont pas recalculables depuis
le catalogue, qui peut avoir changé depuis.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c2e4f1b936"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_version_snapshot",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", sa.UUID(as_uuid=True), nullable=False,
                  comment="Tenant propriétaire de l'instantané (BE-075)."),
        sa.Column("planRef", sa.String(length=100), nullable=False, comment="Code du plan capturé."),
        sa.Column("planVersion", sa.Integer(), nullable=False, comment="Numéro de la version capturée."),
        sa.Column("capturedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sourceCatalogueRef", sa.String(length=64), nullable=False,
                  comment="Identifiant de la ligne planVersion source."),
        sa.Column("snapshotJson", sa.JSON(), nullable=False, comment="Contenu figé de l'offre et de sa version."),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        comment="Instantané immuable d'une version d'offre, capturé au devis ou au contrat (BE-075).",
    )
    op.create_index("ix_plan_version_snapshot_organizationId", "plan_version_snapshot", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_plan_version_snapshot_organizationId", table_name="plan_version_snapshot")
    op.drop_table("plan_version_snapshot")
