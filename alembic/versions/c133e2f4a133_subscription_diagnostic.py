"""Table des diagnostics abonnement guidés (BE-133).

Revision ID: c133e2f4a133
Revises: 5e31981cf46c
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c133e2f4a133"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_diagnostic",
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
        sa.CheckConstraint("result IN ('conforme', 'echec', 'non_concluant')", name="ck_subscription_diagnostic_result"),
        sa.CheckConstraint(
            '"verificationStatus" IN (\'verifiee\', \'non_verifiee\')',
            name="ck_subscription_diagnostic_verification",
        ),
        sa.CheckConstraint(
            '"failurePath" IS NULL OR "failurePath" IN (\'reprise\', \'escalade\')',
            name="ck_subscription_diagnostic_failure_path",
        ),
        sa.ForeignKeyConstraint(["caseId"], ["intervention_case.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Diagnostic abonnement guidé, lecture seule, rattaché à un cas d'intervention (BE-133).",
    )
    op.create_index("ix_subscription_diagnostic_caseId", "subscription_diagnostic", ["caseId"])


def downgrade() -> None:
    op.drop_index("ix_subscription_diagnostic_caseId", table_name="subscription_diagnostic")
    op.drop_table("subscription_diagnostic")
