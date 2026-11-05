"""Table capacity_samples : mesures de capacité par service et tenant (BE-255).

Migration purement additive : crée la table d'échantillons. Aucune donnée existante
n'est modifiée. La table est alimentée par `enregistrer_mesure` (app/operator/capacite.py).

Réversibilité : downgrade() supprime la table. Les échantillons sont des mesures
techniques et non des données métier : leur perte n'affecte aucun document ni droit.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c25e5b1d03"
down_revision = "f9d7ef17ec72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_samples",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("service", sa.String(length=120), nullable=False),
        sa.Column("tenantId", sa.Uuid(), nullable=False),
        sa.Column("latencyMs", sa.Float(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("sizeBytes", sa.Integer(), nullable=False),
        sa.Column("attributedCostCents", sa.Integer(), nullable=False),
        sa.Column("measuredAt", sa.DateTime(timezone=True), nullable=False),
        comment="Échantillons de latence, concurrence, taille et coût attribué par service et tenant (BE-255).",
    )


def downgrade() -> None:
    op.drop_table("capacity_samples")
