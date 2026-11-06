"""BE-117 : table export_job (exports de données asynchrones du portail).

Revision ID: c117e5a1b2d3
Revises: 24165cba1ba6
Create Date: 2026-11-06

Une ligne par demande d'export d'une organisation : demandeur, périmètre, statut parmi
`export_requested`, `ready`, `expired`, contenu (JSON, purgé à l'expiration) et échéance
`expiresAt` (NULL tant que l'export n'est pas prêt). Table distincte de `export_jobs` (BE-243)
et de `job` (BE-213).
Downgrade : suppression de la table, sans effet sur les autres tables d'export.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c117e5a1b2d3"
down_revision = "24165cba1ba6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("requestedBy", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("perimetre", sa.String(length=32), nullable=False),
        sa.Column("statut", sa.String(length=32), server_default="export_requested", nullable=False),
        sa.Column("contenu", sa.JSON(), nullable=True),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('export_requested', 'ready', 'expired')", name="ck_export_job_statut"),
        comment="Demande d'export de données asynchrone du portail, à durée de vie limitée (BE-117).",
    )
    op.create_index("ix_export_job_organizationId", "export_job", ["organizationId"])
    op.create_index("ix_export_job_expiresAt", "export_job", ["expiresAt"])


def downgrade() -> None:
    op.drop_index("ix_export_job_expiresAt", table_name="export_job")
    op.drop_index("ix_export_job_organizationId", table_name="export_job")
    op.drop_table("export_job")
