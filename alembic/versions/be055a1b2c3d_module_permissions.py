"""BE-055 : table module_permissions (permissions déclarées par version de module).

Revises: 169de7fb56af
Create Date: 2026-11-04

Une ligne par permission déclarée par une version de module. Unicité (moduleVersionId, code) :
deux versions peuvent déclarer le même code, une version ne le déclare qu'une fois.
Le downgrade supprime la table entière.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "be055a1b2c3d"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    scope = postgresql.ENUM("organization", "tenant", "platform", name="module_permission_scope", create_type=False)
    scope.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "module_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("moduleVersionId", postgresql.UUID(as_uuid=True), sa.ForeignKey("module_version.id"), nullable=False),
        sa.Column("code", sa.String(length=150), nullable=False, comment="Code de permission (domaine.entite.action)."),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("scope", scope, nullable=False, comment="Portée de la permission (organization, tenant, platform)."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("moduleVersionId", "code", name="uq_module_permissions_version_code"),
        comment="Permissions déclarées par chaque version d'un module (BE-055).",
    )
    op.create_index("ix_module_permissions_moduleVersionId", "module_permissions", ["moduleVersionId"])


def downgrade() -> None:
    op.drop_index("ix_module_permissions_moduleVersionId", table_name="module_permissions")
    op.drop_table("module_permissions")
    postgresql.ENUM(name="module_permission_scope").drop(op.get_bind(), checkfirst=True)
