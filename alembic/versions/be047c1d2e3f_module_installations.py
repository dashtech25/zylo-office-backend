"""Installations techniques de modules par organisation (BE-047).

Crée la table `module_installations` : une ligne par installation d'une version de module pour une
organisation. Un index unique partiel garantit au plus une installation non `removed` par
(organisation, module). `operationId` est unique : il identifie l'opération pour sa relecture.

Revision ID: be047c1d2e3f
Revises: 12b9bd0b8c15
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "be047c1d2e3f"
down_revision: str | None = "12b9bd0b8c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_installations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organizationId", sa.UUID(), nullable=False, comment="Organisation (tenant) qui installe le module."),
        sa.Column("moduleId", sa.UUID(), nullable=False),
        sa.Column(
            "moduleVersionId",
            sa.UUID(),
            nullable=False,
            comment="Version installée ; doit être publiée et compatible au moment de l'installation.",
        ),
        sa.Column(
            "state",
            sa.String(length=50),
            server_default="not_installed",
            nullable=False,
            comment="État courant de l'installation (matrice d'états, BE-041).",
        ),
        sa.Column("stateVersion", sa.Integer(), server_default="0", nullable=False, comment="Version d'état : nombre de transitions journalisées."),
        sa.Column("operationId", sa.UUID(), nullable=False, comment="Identifiant de l'opération d'installation (relecture par GET)."),
        sa.Column("lastErrorCode", sa.String(length=100), nullable=True, comment="Code d'erreur de la dernière étape en échec."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.ForeignKeyConstraint(["moduleId"], ["module.id"]),
        sa.ForeignKeyConstraint(["moduleVersionId"], ["module_version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operationId"),
        comment="Installations techniques des modules par organisation (BE-047).",
    )
    op.create_index(op.f("ix_module_installations_organizationId"), "module_installations", ["organizationId"], unique=False)
    op.create_index(op.f("ix_module_installations_moduleId"), "module_installations", ["moduleId"], unique=False)
    op.create_index(op.f("ix_module_installations_moduleVersionId"), "module_installations", ["moduleVersionId"], unique=False)
    op.create_index(
        "uq_module_installations_organisation_module_actif",
        "module_installations",
        ["organizationId", "moduleId"],
        unique=True,
        postgresql_where=sa.text("state <> 'removed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_module_installations_organisation_module_actif", table_name="module_installations")
    op.drop_index(op.f("ix_module_installations_moduleVersionId"), table_name="module_installations")
    op.drop_index(op.f("ix_module_installations_moduleId"), table_name="module_installations")
    op.drop_index(op.f("ix_module_installations_organizationId"), table_name="module_installations")
    op.drop_table("module_installations")
