"""BE-095 : tables `reconciliation_run` et `reconciliation_difference` (réconciliation des paiements).

Revision ID: c095a1b2d3e4
Revises: fd57ba293e8b

Deux tables nouvelles, aucune modification de table existante. `reconciliation_run` porte le
périmètre (`organizationId`, CA-4), la période indicative et le nombre d'écarts. Les écarts
(`reconciliation_difference`) lient un run à une tentative `paymentAttempt` ; l'unicité
(run, tentative) empêche de compter deux fois le même constat dans un run.

Downgrade : supprime les écarts avant les runs (clé étrangère), sans toucher aux tentatives.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c095a1b2d3e4"
down_revision: Union[str, None] = "fd57ba293e8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organizationId", sa.UUID(), nullable=False, comment="Tenant dont les tentatives ont été réconciliées (CA-4)."),
        sa.Column("scope", sa.String(20), nullable=False, comment="Périmètre demandé : tenant."),
        sa.Column("periodKey", sa.String(20), nullable=True, comment="Période indicative fournie par l'appelant."),
        sa.Column("status", sa.String(20), nullable=False, comment="completed."),
        sa.Column("differenceCount", sa.Integer(), nullable=False, server_default="0", comment="Nombre d'écarts créés par ce run."),
        sa.Column("startedAt", sa.DateTime(timezone=True), nullable=False, comment="Instant de lancement du run."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Exécution de réconciliation des paiements et résultats incertains (BE-095).",
    )
    op.create_index(op.f("ix_reconciliation_run_organizationId"), "reconciliation_run", ["organizationId"], unique=False)

    op.create_table(
        "reconciliation_difference",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("runId", sa.UUID(), nullable=False),
        sa.Column("paymentAttemptId", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, comment="detected (aucune correction automatique)."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["runId"], ["reconciliation_run.id"]),
        sa.ForeignKeyConstraint(["paymentAttemptId"], ["paymentAttempt.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runId", "paymentAttemptId", name="uq_reconciliation_difference_run_attempt"),
        comment="Écart constaté par une réconciliation des paiements (BE-095), sans correction automatique.",
    )
    op.create_index(op.f("ix_reconciliation_difference_runId"), "reconciliation_difference", ["runId"], unique=False)
    op.create_index(op.f("ix_reconciliation_difference_paymentAttemptId"), "reconciliation_difference", ["paymentAttemptId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reconciliation_difference_paymentAttemptId"), table_name="reconciliation_difference")
    op.drop_index(op.f("ix_reconciliation_difference_runId"), table_name="reconciliation_difference")
    op.drop_table("reconciliation_difference")
    op.drop_index(op.f("ix_reconciliation_run_organizationId"), table_name="reconciliation_run")
    op.drop_table("reconciliation_run")
