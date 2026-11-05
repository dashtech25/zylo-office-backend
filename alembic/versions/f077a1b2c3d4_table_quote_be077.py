"""table quote : devis d'achat, du tenant bénéficiaire à un payeur (BE-077)

Revision ID: f077a1b2c3d4
Revises: 12b9bd0b8c15
Create Date: 2026-11-04

Migration additive. Crée la table `quote` : id, payerId, beneficiaryTenantId,
planVersionSnapshotId, status, version, expiresAt, createdAt, pricingSnapshotJson.
`expiresAt` reste NULL tant que la durée de validité n'est pas définie (QE-FAC-21).
Aucune donnée existante n'est modifiée.

Retour arrière : suppression de la table. Les devis saisis sont perdus ; le retour
arrière ne doit pas être joué sur une base où des abonnements ont été souscrits
à partir d'un devis accepté, car ce lien n'est alors plus traçable.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f077a1b2c3d4"
down_revision: Union[str, None] = "12b9bd0b8c15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quote",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("payerId", sa.UUID(as_uuid=True), nullable=False,
                  comment="Compte payeur du devis."),
        sa.Column("beneficiaryTenantId", sa.UUID(as_uuid=True), nullable=False,
                  comment="Tenant bénéficiaire, qui porte le devis (scope de lecture)."),
        sa.Column("planVersionSnapshotId", sa.UUID(as_uuid=True), nullable=False,
                  comment="Instantané de l'offre capturé au devis (BE-075)."),
        sa.Column("status", sa.String(length=20), nullable=False,
                  comment="created, priced, accepted, expired ou revoked."),
        sa.Column("version", sa.Integer(), nullable=False,
                  comment="Verrou optimiste (BE-072), incrémenté à chaque transition."),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=True,
                  comment="Fin de validité ; NULL tant que QE-FAC-21 n'est pas tranchée."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("pricingSnapshotJson", sa.JSON(), nullable=True,
                  comment="Prix, devise et taxe figés (BE-078) ; NULL avant priced."),
        sa.ForeignKeyConstraint(["payerId"], ["billing_payer.id"]),
        sa.ForeignKeyConstraint(["beneficiaryTenantId"], ["organization.id"]),
        sa.ForeignKeyConstraint(["planVersionSnapshotId"], ["plan_version_snapshot.id"]),
        comment="Devis d'achat, du tenant bénéficiaire à un payeur (BE-077). Valeurs de durée non définies (QE-FAC-21).",
    )
    op.create_index("ix_quote_beneficiaryTenantId", "quote", ["beneficiaryTenantId"])


def downgrade() -> None:
    op.drop_index("ix_quote_beneficiaryTenantId", table_name="quote")
    op.drop_table("quote")
