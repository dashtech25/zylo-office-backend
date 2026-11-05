"""BE-185 : table `tenant` du cycle de vie plateforme.

Crée `tenant` : clé `tenantId`, slug unique, `state` contraint aux six états du
graphe (requested, provisioning, active, suspended, closing, closed), verrou
`version` (défaut 1), `createdAt`, et `closedAt` renseigné à la fermeture.

Pas de clé étrangère : un tenant précède son organisation racine (QE-API-05).
Aucune donnée n'est reprise ; la table est vide à la création.

Downgrade : suppression de la table. Les tenants et leur historique d'état sont perdus.

Revision ID: b185c0d1e2f3
Revises: e193c0a1b2d3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b185c0d1e2f3"
down_revision: Union[str, None] = "e193c0a1b2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("tenantId", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closedAt", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_tenant_slug"),
        sa.CheckConstraint(
            "state IN ('requested', 'provisioning', 'active', 'suspended', 'closing', 'closed')",
            name="ck_tenant_state",
        ),
        comment="Tenant de la plateforme : cycle de vie (BE-185), état et verrou de version.",
    )


def downgrade() -> None:
    op.drop_table("tenant")
