"""BE-185 : colonnes du cycle de vie sur la table `tenant` (BE-100).

La table `tenant` existe déjà (BE-100, `be100a0b1c2d`) : cette migration ne la
recrée pas. Elle ajoute seulement ce que le cycle de vie plateforme exige :
- `slug` (identifiant lisible, unique) ; les lignes existantes reçoivent
  `tenant-<id>` pour que la colonne reste renseignable ;
- `version` (verrou de version, défaut 1) ;
- `closedAt` (renseigné à la fermeture) ;
- `organizationId` devient facultatif : un tenant précède son organisation racine
  (QE-API-05) ;
- `ck_tenant_state` borne `status` aux six états du graphe.

Downgrade : suppression des colonnes ajoutées et de la contrainte, puis retour de
`organizationId` à NOT NULL. Ce retour supprime d'abord les tenants sans
organisation, qui n'existent que depuis BE-185 : leur historique d'état est perdu.

Revision ID: b185c0d1e2f3
Revises: 54ba4aaf7237
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b185c0d1e2f3"
down_revision: Union[str, None] = "54ba4aaf7237"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("slug", sa.String(100), nullable=True))
    op.execute("UPDATE tenant SET slug = 'tenant-' || id::text WHERE slug IS NULL")
    op.create_unique_constraint("uq_tenant_slug", "tenant", ["slug"])
    op.add_column("tenant", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tenant", sa.Column("closedAt", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("tenant", "organizationId", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_check_constraint(
        "ck_tenant_state",
        "tenant",
        "status IN ('requested', 'provisioning', 'active', 'suspended', 'closing', 'closed')",
    )


def downgrade() -> None:
    op.execute('DELETE FROM tenant WHERE "organizationId" IS NULL')
    op.drop_constraint("ck_tenant_state", "tenant", type_="check")
    op.alter_column("tenant", "organizationId", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("tenant", "closedAt")
    op.drop_column("tenant", "version")
    op.drop_constraint("uq_tenant_slug", "tenant", type_="unique")
    op.drop_column("tenant", "slug")
