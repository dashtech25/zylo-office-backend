"""job de renouvellement d'abonnement (BE-089)

Revision ID: c4089b2a1e7f
Revises: a2456e1f2b3c
Create Date: 2026-11-05 16:00:00.000000

Crée la table `renewal_run` : un passage du job de renouvellement par abonnement,
période et type. La contrainte unique (subscriptionId, periodKey, type) est la clé de
déduplication de la fiche BE-089 : rejouer une période ne crée jamais un second passage.
Aucune donnée n'est créée ni modifiée.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c4089b2a1e7f"
down_revision = "a2456e1f2b3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)
    op.create_table(
        "renewal_run",
        sa.Column("id", uuid_t, nullable=False),
        sa.Column("subscriptionId", uuid_t, nullable=False, comment="Abonnement renouvelé."),
        sa.Column("periodKey", sa.String(length=20), nullable=False, comment="Clé de période de facturation, opaque pour le job."),
        sa.Column("type", sa.String(length=40), nullable=False, comment="Type de passage ; `renewal` pour BE-089."),
        sa.Column("status", sa.String(length=20), nullable=False, comment="completed | refused."),
        sa.Column("attemptedAt", sa.DateTime(timezone=True), nullable=False, comment="Instant du premier passage pour cette clé."),
        sa.Column("invoiceId", uuid_t, nullable=True, comment="Facture émise par ce passage ; NULL si refusé."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["subscriptionId"], ["subscription.id"]),
        sa.ForeignKeyConstraint(["invoiceId"], ["invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscriptionId", "periodKey", "type", name="uq_renewal_run_key"),
        comment="Passage du job de renouvellement d'abonnement (BE-089), une ligne par abonnement, période et type.",
    )
    op.create_index(op.f("ix_renewal_run_subscriptionId"), "renewal_run", ["subscriptionId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_renewal_run_subscriptionId"), table_name="renewal_run")
    op.drop_table("renewal_run")
