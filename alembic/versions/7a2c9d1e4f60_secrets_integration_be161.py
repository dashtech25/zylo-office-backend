"""stockage séparé des secrets d'intégration (BE-161) : table secret_integration

Revision ID: 7a2c9d1e4f60
Revises: 5e31981cf46c
Create Date: 2026-11-05 12:00:00.000000

Crée la table `secret_integration` : une ligne par version de secret d'un connecteur,
désignée par `referenceSecret`. Aucune colonne ne porte la valeur du secret : elle vit
dans le coffre, jamais en base. `expireAt` est nullable (QE-PAR-09).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a2c9d1e4f60"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "secret_integration",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("connecteurId", sa.UUID(as_uuid=True), sa.ForeignKey("connecteur.id"), nullable=False),
        sa.Column("referenceSecret", sa.String(length=255), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expireAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('"version" >= 1', name="ck_secret_integration_version_positive"),
        sa.CheckConstraint(
            "length(btrim(\"referenceSecret\")) > 0", name="ck_secret_integration_reference_non_vide"
        ),
        sa.UniqueConstraint("connecteurId", "version", name="uq_secret_integration_connecteur_version"),
        comment="Références des secrets d'intégration, jamais de valeur (BE-161).",
    )
    op.create_index("ix_secret_integration_connecteurId", "secret_integration", ["connecteurId"])


def downgrade() -> None:
    op.drop_index("ix_secret_integration_connecteurId", table_name="secret_integration")
    op.drop_table("secret_integration")
