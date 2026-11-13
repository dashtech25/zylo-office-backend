"""liens d'intégrations externes : références, curseur et réconciliation (BE-239)

Revision ID: be239a1b2c3d
Revises: f9d7ef17ec72
Create Date: 2026-11-05 14:00:00.000000

Table `integration_links` : un lien par connexion d'un tenant à un compte externe.
Aucune valeur de secret : `connecteurId` pointe vers le connecteur dont le secret est
dans le coffre (BE-161). Contraintes : statut et résultat de réconciliation bornés par
CHECK ; unicité du compte par tenant ; un seul lien par connecteur.
Downgrade : suppression de la table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "be239a1b2c3d"
down_revision: Union[str, None] = "f9d7ef17ec72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("connecteurId", postgresql.UUID(as_uuid=True), sa.ForeignKey("connecteur.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("externalAccount", sa.String(length=128), nullable=False),
        sa.Column("remoteKey", sa.String(length=512), nullable=False),
        sa.Column("statut", sa.String(length=16), nullable=False, server_default="connectée"),
        sa.Column("curseurSync", sa.String(length=255), nullable=True),
        sa.Column("derniereReconciliation", sa.DateTime(timezone=True), nullable=True),
        sa.Column("statutReconciliation", sa.String(length=16), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("statut IN ('connectée', 'déconnectée')", name="ck_integration_links_statut"),
        sa.CheckConstraint(
            "\"statutReconciliation\" IS NULL OR \"statutReconciliation\" IN ('succes', 'echec')",
            name="ck_integration_links_statut_reconciliation",
        ),
        sa.CheckConstraint("length(btrim(\"remoteKey\")) > 0", name="ck_integration_links_remote_key_non_vide"),
        sa.UniqueConstraint("organizationId", "provider", "externalAccount", name="uq_integration_links_tenant_compte"),
        sa.UniqueConstraint("connecteurId", name="uq_integration_links_connecteur"),
        comment="Liens tenant vers des comptes de fournisseurs externes, sans secret (BE-239).",
    )
    op.create_index("ix_integration_links_organizationId", "integration_links", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_integration_links_organizationId", table_name="integration_links")
    op.drop_table("integration_links")
