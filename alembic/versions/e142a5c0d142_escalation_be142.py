"""Table `escalation` et état `escalade` des cas d'intervention (BE-142).

Revision ID: e142a5c0d142
Revises: f9d7ef17ec72
Create Date: 2026-11-05

- crée `escalation` : une ligne par escalade ouverte sur un cas (`caseId`), avec le
  niveau (1 à 3, QE-ADM-12), le rôle cible, l'ouverture et, à la clôture, `closedAtUtc`
  et `closureReason` ;
- élargit la contrainte `ck_intervention_case_status` de BE-123 pour accepter
  `escalade`.

Downgrade : les cas à l'état `escalade` repassent à `affecte` (s'ils ont un assigné)
ou à `ouvert`, puis l'ancienne contrainte est rétablie et la table est supprimée.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e142a5c0d142"
down_revision: Union[str, None] = "f9d7ef17ec72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escalation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("caseId", sa.UUID(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("targetRole", sa.String(length=64), nullable=False),
        sa.Column("openedAtUtc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closedAtUtc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closureReason", sa.String(length=500), nullable=True),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_escalation_level"),
        sa.ForeignKeyConstraint(["caseId"], ["intervention_case.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Escalades d'un cas d'intervention, ouvertes et closes par les agents (BE-142).",
    )
    op.create_index("ix_escalation_caseId", "escalation", ["caseId"])

    op.drop_constraint("ck_intervention_case_status", "intervention_case", type_="check")
    op.create_check_constraint(
        "ck_intervention_case_status",
        "intervention_case",
        "status IN ('ouvert', 'affecte', 'escalade', 'cloture')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE intervention_case SET status = "
        "CASE WHEN \"assigneeId\" IS NULL THEN 'ouvert' ELSE 'affecte' END "
        "WHERE status = 'escalade'"
    )
    op.drop_constraint("ck_intervention_case_status", "intervention_case", type_="check")
    op.create_check_constraint(
        "ck_intervention_case_status",
        "intervention_case",
        "status IN ('ouvert', 'affecte', 'cloture')",
    )
    op.drop_index("ix_escalation_caseId", table_name="escalation")
    op.drop_table("escalation")
