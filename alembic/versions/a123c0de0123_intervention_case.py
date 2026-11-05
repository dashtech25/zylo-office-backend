"""Table des cas d'intervention de support (BE-123).

Revision ID: a123c0de0123
Revises: 934346a13edd
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a123c0de0123"
down_revision: Union[str, None] = "934346a13edd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intervention_case",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenantId", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="ouvert", nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("qualification", sa.String(length=200), nullable=False),
        sa.Column("openedBy", sa.UUID(), nullable=False),
        sa.Column("assigneeId", sa.UUID(), nullable=True),
        sa.Column("consentRef", sa.String(length=120), nullable=True),
        sa.Column("openedAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closedAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closureReason", sa.String(length=500), nullable=True),
        sa.CheckConstraint("priority IN ('basse', 'normale', 'haute')", name="ck_intervention_case_priority"),
        sa.CheckConstraint("status IN ('ouvert', 'affecte', 'cloture')", name="ck_intervention_case_status"),
        sa.ForeignKeyConstraint(["tenantId"], ["organization.id"]),
        sa.ForeignKeyConstraint(["openedBy"], ["user.id"]),
        sa.ForeignKeyConstraint(["assigneeId"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Cas d'intervention de support, ouvert et clos par les agents administratifs (BE-123).",
    )
    op.create_index("ix_intervention_case_tenantId", "intervention_case", ["tenantId"])
    op.create_index("ix_intervention_case_openedBy", "intervention_case", ["openedBy"])
    op.create_index("ix_intervention_case_assigneeId", "intervention_case", ["assigneeId"])


def downgrade() -> None:
    op.drop_index("ix_intervention_case_assigneeId", table_name="intervention_case")
    op.drop_index("ix_intervention_case_openedBy", table_name="intervention_case")
    op.drop_index("ix_intervention_case_tenantId", table_name="intervention_case")
    op.drop_table("intervention_case")
