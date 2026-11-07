"""configuration d'intégration et références de credential (BE-210)

Revision ID: be210c0d1e2f
Revises: 24165cba1ba6
Create Date: 2026-11-06 10:00:00.000000

Tables `integration` (une configuration par fournisseur et usage, par organisation) et
`integration_credential` (une ligne par version de secret, référence au coffre seulement).
Aucune valeur de secret n'est stockée. Contraintes : état borné par CHECK, unicité
(organisation, fournisseur, usage), unicité (intégration, version).
Downgrade : suppression des deux tables, dans l'ordre inverse de création.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "be210c0d1e2f"
down_revision: Union[str, None] = "24165cba1ba6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("configSchemaVersion", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="configured"),
        sa.Column("credentialRef", sa.String(length=255), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('configured', 'active', 'degraded', 'revoked')", name="ck_integration_state"
        ),
        sa.CheckConstraint("\"configSchemaVersion\" >= 1", name="ck_integration_config_schema_version_positive"),
        sa.CheckConstraint("length(btrim(provider)) > 0", name="ck_integration_provider_non_vide"),
        sa.CheckConstraint("length(btrim(purpose)) > 0", name="ck_integration_purpose_non_vide"),
        sa.UniqueConstraint(
            "organizationId", "provider", "purpose", name="uq_integration_organisation_fournisseur_usage"
        ),
        comment="Configuration d'intégration par tenant, référence de credential sans valeur (BE-210).",
    )
    op.create_index("ix_integration_organizationId", "integration", ["organizationId"])

    op.create_table(
        "integration_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("integrationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("integration.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("referenceSecret", sa.String(length=255), nullable=False, unique=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint('"version" >= 1', name="ck_integration_credential_version_positive"),
        sa.CheckConstraint(
            "length(btrim(\"referenceSecret\")) > 0", name="ck_integration_credential_reference_non_vide"
        ),
        sa.UniqueConstraint("integrationId", "version", name="uq_integration_credential_version"),
        comment="Versions de credential d'intégration : références au coffre, jamais de valeur (BE-210).",
    )
    op.create_index("ix_integration_credential_integrationId", "integration_credential", ["integrationId"])


def downgrade() -> None:
    op.drop_index("ix_integration_credential_integrationId", table_name="integration_credential")
    op.drop_table("integration_credential")
    op.drop_index("ix_integration_organizationId", table_name="integration")
    op.drop_table("integration")
