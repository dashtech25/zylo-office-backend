"""Routage des alertes d'exploitation : table alert_routes (BE-241).

Migration purement additive : crée la table de configuration. Aucune ligne n'est
seedée ici, car la configuration provisoire est appliquée par le service
(`appliquer_routes_provisoires`) et les tests de schéma purgent la base après
upgrade.

Réversibilité : downgrade() supprime la table ; c'est une configuration, pas une
donnée métier, donc aucune donnée utilisateur n'est perdue.
"""

import sqlalchemy as sa
from alembic import op

revision = "d51b3bc6fe0c"
down_revision = "169de7fb56af"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_routes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("signal", sa.String(length=120), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("runbook", sa.String(length=300), nullable=False),
        sa.Column("escalation", sa.Text(), nullable=True),
        sa.UniqueConstraint("signal", name="uq_alert_routes_signal"),
        sa.CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_alert_routes_severity"),
        comment="Routage des signaux d'exploitation vers le propriétaire, le runbook et l'escalade.",
    )


def downgrade() -> None:
    op.drop_table("alert_routes")
