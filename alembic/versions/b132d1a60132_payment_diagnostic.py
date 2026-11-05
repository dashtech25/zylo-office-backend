"""Table des diagnostics paiement guidés (BE-132).

Revision ID: b132d1a60132
Revises: 3a2990daf8ef
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b132d1a60132"
down_revision: Union[str, None] = "3a2990daf8ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_diagnostic",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("caseId", sa.UUID(), nullable=False),
        sa.Column("qualification", sa.String(length=200), nullable=False),
        sa.Column("proofConsultedRef", sa.String(length=200), nullable=False),
        sa.Column("permittedAction", sa.String(length=40), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("verificationStatus", sa.String(length=16), nullable=False),
        sa.Column("failurePath", sa.String(length=16), nullable=True),
        sa.Column("escalationId", sa.UUID(), nullable=True),
        sa.Column("closedAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("result IN ('conforme', 'echec', 'non_concluant')", name="ck_payment_diagnostic_result"),
        sa.CheckConstraint(
            '"verificationStatus" IN (\'verifiee\', \'non_verifiee\')',
            name="ck_payment_diagnostic_verification",
        ),
        sa.CheckConstraint(
            '"failurePath" IS NULL OR "failurePath" IN (\'reprise\', \'escalade\')',
            name="ck_payment_diagnostic_failure_path",
        ),
        sa.ForeignKeyConstraint(["caseId"], ["intervention_case.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Diagnostic paiement guidé, lecture seule, rattaché à un cas d'intervention (BE-132).",
    )
    op.create_index("ix_payment_diagnostic_caseId", "payment_diagnostic", ["caseId"])


def downgrade() -> None:
    op.drop_index("ix_payment_diagnostic_caseId", table_name="payment_diagnostic")
    op.drop_table("payment_diagnostic")
