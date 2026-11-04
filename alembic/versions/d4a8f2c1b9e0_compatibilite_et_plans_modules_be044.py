"""Compatibilité et plans de mise à jour des modules (BE-044)

Revision ID: d4a8f2c1b9e0
Revises: 169de7fb56af
Create Date: 2026-11-04

Intention : ajouter deux tables, et rien d'autre.
- `module_compatibility_evaluations` : une ligne par évaluation de compatibilité d'une version
  (résultat compatible/incompatible/unknown, motifs). Append-only.
- `module_upgrade_plans` : plans de passage entre deux versions, calculés sans exécution.

Migration purement additive : aucune table existante n'est modifiée. Le downgrade supprime les
deux tables et le type d'énumération créé pour le résultat ; les évaluations journalisées sont
donc perdues, ce qui est attendu pour une table ajoutée par cette migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a8f2c1b9e0"
down_revision: str | None = "169de7fb56af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESULTAT_COMPATIBILITE = postgresql.ENUM(
    "compatible", "incompatible", "unknown", name="module_compatibility_result", create_type=False
)


def upgrade() -> None:
    RESULTAT_COMPATIBILITE.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "module_compatibility_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "moduleVersionId",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("module_version.id"),
            nullable=False,
            comment="Version évaluée.",
        ),
        sa.Column("result", RESULTAT_COMPATIBILITE, nullable=False, comment="Résultat de l'évaluation."),
        sa.Column("reasons", sa.JSON(), nullable=False, comment="Motifs de l'évaluation."),
        sa.Column(
            "evaluatedAt",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Date de l'évaluation.",
        ),
        comment="Évaluations de compatibilité des versions de module (BE-044), append-only.",
    )
    op.create_index(
        "ix_module_compatibility_evaluations_moduleVersionId",
        "module_compatibility_evaluations",
        ["moduleVersionId"],
    )

    op.create_table(
        "module_upgrade_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("moduleId", postgresql.UUID(as_uuid=True), sa.ForeignKey("module.id"), nullable=False),
        sa.Column("fromVersion", sa.String(length=50), nullable=False),
        sa.Column("toVersion", sa.String(length=50), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False, comment="Étapes ordonnées du plan."),
        sa.Column("rollbackPossible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("forwardOnly", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("createdAt", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        comment="Plans de mise à jour de module, calculés sans exécution (BE-044).",
    )
    op.create_index("ix_module_upgrade_plans_moduleId", "module_upgrade_plans", ["moduleId"])


def downgrade() -> None:
    op.drop_index("ix_module_upgrade_plans_moduleId", table_name="module_upgrade_plans")
    op.drop_table("module_upgrade_plans")
    op.drop_index(
        "ix_module_compatibility_evaluations_moduleVersionId",
        table_name="module_compatibility_evaluations",
    )
    op.drop_table("module_compatibility_evaluations")
    RESULTAT_COMPATIBILITE.drop(op.get_bind(), checkfirst=True)
