"""BE-243 : table export_jobs (export de données par sujet ou tenant).

Revision ID: a243b0c1d2e3
Revises: 290f30a9bcbf
Create Date: 2026-11-05 10:00:00.000000

Crée `export_jobs` : un job par demande d'export, avec périmètre, statut, échéance,
empreinte SHA-256 et contenu purgeable à l'expiration (voir app/exports/models.py).
Downgrade : suppression de la table, donc des jobs en cours (aucune donnée source n'est touchée).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a243b0c1d2e3"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("demandeur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("perimetre", sa.JSON(), nullable=False),
        sa.Column("statut", sa.String(length=16), server_default="pret", nullable=False),
        sa.Column("expireAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("empreinte", sa.String(length=64), nullable=False),
        sa.Column("contenu", sa.JSON(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('pret', 'expire')", name="ck_export_jobs_statut"),
        sa.CheckConstraint("length(empreinte) = 64", name="ck_export_jobs_empreinte_sha256"),
        comment="Job d'export de données par sujet ou tenant, à durée de vie limitée (BE-243).",
    )
    op.create_index(op.f("ix_export_jobs_organizationId"), "export_jobs", ["organizationId"], unique=False)
    op.create_index(op.f("ix_export_jobs_expireAt"), "export_jobs", ["expireAt"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_export_jobs_expireAt"), table_name="export_jobs")
    op.drop_index(op.f("ix_export_jobs_organizationId"), table_name="export_jobs")
    op.drop_table("export_jobs")
