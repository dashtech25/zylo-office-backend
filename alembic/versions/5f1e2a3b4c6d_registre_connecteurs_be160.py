"""registre des connecteurs (BE-160) : table connecteur

Revision ID: 5f1e2a3b4c6d
Revises: 12a5bb79f642
Create Date: 2026-11-05 12:00:00.000000

Crée la table `connecteur` : portée (tenant ou global), rattachement `organizationId`
(nul exactement pour le global), état parmi création, activé, suspendu, révoqué, et
version de configuration. Aucune donnée secrète n'est stockée.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5f1e2a3b4c6d"
down_revision: Union[str, None] = "12a5bb79f642"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connecteur",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("portee", sa.String(length=16), nullable=False),
        sa.Column("organizationId", sa.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=True),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("etat", sa.String(length=16), nullable=False),
        sa.Column("versionConfiguration", sa.Integer(), server_default="1", nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("portee IN ('tenant', 'global')", name="ck_connecteur_portee"),
        sa.CheckConstraint(
            "etat IN ('création', 'activé', 'suspendu', 'révoqué')",
            name="ck_connecteur_etat",
        ),
        sa.CheckConstraint(
            "(portee = 'global' AND \"organizationId\" IS NULL) "
            "OR (portee = 'tenant' AND \"organizationId\" IS NOT NULL)",
            name="ck_connecteur_portee_organisation",
        ),
        sa.CheckConstraint("length(btrim(nom)) > 0", name="ck_connecteur_nom_non_vide"),
        sa.CheckConstraint('"versionConfiguration" >= 1', name="ck_connecteur_version_positive"),
        comment="Registre des connecteurs : portée, état et version de configuration (BE-160).",
    )
    op.create_index("ix_connecteur_organizationId", "connecteur", ["organizationId"])
    op.create_index("ix_connecteur_organizationId_etat", "connecteur", ["organizationId", "etat"])


def downgrade() -> None:
    op.drop_index("ix_connecteur_organizationId_etat", table_name="connecteur")
    op.drop_index("ix_connecteur_organizationId", table_name="connecteur")
    op.drop_table("connecteur")
