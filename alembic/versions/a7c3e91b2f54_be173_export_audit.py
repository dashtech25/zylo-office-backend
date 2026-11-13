"""BE-173 : table export_audit (job d'export du journal d'audit, rétention).

Revision ID: a7c3e91b2f54
Revises: 5e31981cf46c
Create Date: 2026-11-05

Une ligne par demande d'export : demandeur, sujet, période (JSON), motif obligatoire,
statut et expiration. Le fichier d'export n'est pas stocké (voir app/audit/export_job.py).
Downgrade : suppression de la table, sans effet sur `audit_event`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c3e91b2f54"
down_revision = "5e31981cf46c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("demandeur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("sujet", sa.String(length=100), nullable=False),
        sa.Column("periode", sa.JSON(), nullable=False),
        sa.Column("motif", sa.String(length=500), nullable=False),
        sa.Column("statut", sa.String(length=16), server_default="pret", nullable=False),
        sa.Column("creeAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expireAt", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(motif)) > 0", name="ck_export_audit_motif_non_vide"),
        sa.CheckConstraint("length(btrim(sujet)) > 0", name="ck_export_audit_sujet_non_vide"),
        sa.CheckConstraint("statut IN ('pret')", name="ck_export_audit_statut"),
        comment="Job d'export du journal d'audit : demandeur, sujet, période, motif, expiration (BE-173).",
    )
    op.create_index("ix_export_audit_organizationId", "export_audit", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_export_audit_organizationId", table_name="export_audit")
    op.drop_table("export_audit")
