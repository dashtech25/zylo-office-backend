"""Table des releases versionnées et de leur promotion (BE-250).

Objectif : garder, par environnement, la trace de l'artefact promu (version, hash, source,
SBOM, gates), de son approbation et de l'horodatage, pour que le rollback sache quelle
release et quelle configuration restaurer.

Réversibilité : oui. Le downgrade supprime la table entière ; il est destructif pour
l'historique des releases, à n'exécuter qu'avec le marqueur de confirmation habituel.
Migration additive : aucune table existante n'est modifiée.

Revision ID: a250b1c2d3e4
Revises: 169de7fb56af
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a250b1c2d3e4"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "release_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("hash_artefact", sa.String(length=64), nullable=False),
        sa.Column("reference_source", sa.String(length=255), nullable=False),
        sa.Column("sbom_reference", sa.String(length=255), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("resultats_gates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("environnement", sa.String(length=32), nullable=False),
        sa.Column("demandeur_id", sa.UUID(), nullable=False),
        sa.Column("approbateur_id", sa.UUID(), nullable=False),
        sa.Column("promue_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", "environnement", name="uq_release_records_version_environnement"),
        comment="Releases versionnées : hash d'artefact, provenance, gates et approbation par environnement.",
    )
    op.create_index(op.f("ix_release_records_version"), "release_records", ["version"], unique=False)
    op.create_index(op.f("ix_release_records_environnement"), "release_records", ["environnement"], unique=False)
    op.create_index(op.f("ix_release_records_promue_le"), "release_records", ["promue_le"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_release_records_promue_le"), table_name="release_records")
    op.drop_index(op.f("ix_release_records_environnement"), table_name="release_records")
    op.drop_index(op.f("ix_release_records_version"), table_name="release_records")
    op.drop_table("release_records")
