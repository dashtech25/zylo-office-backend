"""BE-098 : table data_export_request (demandes d'export des données de facturation)

Revision ID: b098e0f1a2c3
Revises: 254220e168b5
Create Date: 2026-11-05

Crée `data_export_request` : une ligne par demande d'export d'un compte payeur. Colonnes
prévues par BE-098 (`scope`, `requestedBy`, `status`, `requestedAt`, `fileRef`), plus
`organizationId` (tenant bénéficiaire, isolation CA-4) et `accountId` (compte payeur exporté),
nécessaires pour borner l'export au scope demandé. Les colonnes sont en camelCase, la table en
snake_case (décision du propriétaire, QE-FAC-31). Aucune donnée n'est copiée depuis d'autres tables.

Downgrade : retire les index puis la table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b098e0f1a2c3"
down_revision: Union[str, None] = "254220e168b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_export_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False,
                  comment="Identifiant de la demande d'export."),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False,
                  comment="Tenant bénéficiaire dans lequel la demande est faite."),
        sa.Column("accountId", postgresql.UUID(as_uuid=True), sa.ForeignKey("billing_payer.id"), nullable=False,
                  comment="Compte payeur dont les données sont exportées."),
        sa.Column("scope", sa.String(length=30), nullable=False,
                  comment="Périmètre exporté (payeur)."),
        sa.Column("requestedBy", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False,
                  comment="Personne qui a demandé l'export."),
        sa.Column("status", sa.String(length=30), nullable=False,
                  comment="État de la demande (ready)."),
        sa.Column("requestedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
                  comment="Heure serveur de la demande."),
        sa.Column("fileRef", sa.String(length=255), nullable=True,
                  comment="Référence du fichier produit ; NULL tant qu'aucun stockage n'est branché (QE-FAC-25)."),
        comment="Demande d'export des données de facturation d'un compte payeur (BE-098).",
    )
    op.create_index("ix_data_export_request_organizationId", "data_export_request", ["organizationId"])
    op.create_index("ix_data_export_request_accountId", "data_export_request", ["accountId"])
    op.create_index("ix_data_export_request_requestedBy", "data_export_request", ["requestedBy"])


def downgrade() -> None:
    op.drop_index("ix_data_export_request_requestedBy", table_name="data_export_request")
    op.drop_index("ix_data_export_request_accountId", table_name="data_export_request")
    op.drop_index("ix_data_export_request_organizationId", table_name="data_export_request")
    op.drop_table("data_export_request")
