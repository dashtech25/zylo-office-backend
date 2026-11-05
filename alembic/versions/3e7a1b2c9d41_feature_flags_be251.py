"""Feature flags serveur et journal de changements (BE-251).

Crée `feature_flags` (un état par flag et par tenant, défaut sûr, propriétaire et
expiration obligatoires) et `flag_changes` (audit append-only applicatif).

Downgrade : supprime les deux tables. Perte de données assumée : les flags et
leur journal ne sont pas reconstructibles après retour arrière.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3e7a1b2c9d41"
down_revision = "290f30a9bcbf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cle", sa.String(length=100), nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column("defaut_actif", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("proprietaire_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cle", "organization_id", name="uq_feature_flags_cle_organisation"),
        comment="Feature flags par tenant : état, défaut sûr, propriétaire et expiration (BE-251).",
    )
    op.create_index("ix_feature_flags_cle", "feature_flags", ["cle"])

    op.create_table(
        "flag_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cle", sa.String(length=100), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("acteur_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ancien_actif", sa.Boolean(), nullable=True),
        sa.Column("nouvel_actif", sa.Boolean(), nullable=False),
        sa.Column("proprietaire_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        comment="Journal des changements de feature flags (BE-251, audit).",
    )
    op.create_index("ix_flag_changes_cle", "flag_changes", ["cle"])
    op.create_index("ix_flag_changes_organization_id", "flag_changes", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_flag_changes_organization_id", table_name="flag_changes")
    op.drop_index("ix_flag_changes_cle", table_name="flag_changes")
    op.drop_table("flag_changes")
    op.drop_index("ix_feature_flags_cle", table_name="feature_flags")
    op.drop_table("feature_flags")
