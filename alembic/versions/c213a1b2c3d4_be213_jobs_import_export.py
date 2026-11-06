"""BE-213 : tables job et job_error_report (jobs d'import et d'export).

Revision ID: c213a1b2c3d4
Revises: b189c0de0189
Create Date: 2026-11-06 10:00:00.000000

Crée `job` (une ligne par demande, isolée par tenant, clé d'idempotence unique par tenant) et
`job_error_report` (erreurs de traitement rattachées au job). Voir app/jobs/models.py.
Downgrade : suppression des deux tables, donc des jobs et de leurs rapports d'erreurs ; aucune
donnée source ni fichier stocké n'est touché.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c213a1b2c3d4"
down_revision: Union[str, None] = "b189c0de0189"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("jobId", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenantId", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("actorId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("manifestSchemaVersion", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("idempotencyKey", sa.String(length=128), nullable=True),
        sa.Column("filePointer", sa.String(length=512), nullable=True),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')",
            name="ck_job_state",
        ),
        sa.UniqueConstraint("tenantId", "idempotencyKey", name="uq_job_tenant_idempotencyKey"),
        comment="Job d'import ou d'export d'un tenant, rejouable par clé d'idempotence (BE-213).",
    )
    op.create_index(op.f("ix_job_tenantId"), "job", ["tenantId"], unique=False)

    op.create_table(
        "job_error_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("jobId", postgresql.UUID(as_uuid=True), sa.ForeignKey("job.jobId", ondelete="CASCADE"), nullable=False),
        sa.Column("ligne", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Rapport d'erreurs d'un job d'import ou d'export (BE-213).",
    )
    op.create_index(op.f("ix_job_error_report_jobId"), "job_error_report", ["jobId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_error_report_jobId"), table_name="job_error_report")
    op.drop_table("job_error_report")
    op.drop_index(op.f("ix_job_tenantId"), table_name="job")
    op.drop_table("job")
