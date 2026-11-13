"""BE-040 : catalogue de modules (publication, visibilité, versions).

Ajoute à la table `module` (BE-021) les colonnes `publicationState` et `visibility`, avec leurs
enums PostgreSQL, puis crée `module_version` (unicité `(moduleId, version)`).
Les lignes existantes reçoivent les défauts `draft` et `hidden` : aucun module n'est publié
par cette migration.

Revision ID: b040c4a10e01
Revises: 73136cdbf00b
Create Date: 2026-11-03 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b040c4a10e01"
down_revision: Union[str, None] = "73136cdbf00b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ETATS_PUBLICATION = ("draft", "review", "published", "deprecated", "withdrawn", "quarantined")
VISIBILITES = ("hidden", "visible", "restricted")


def upgrade() -> None:
    bind = op.get_bind()
    etat_publication = sa.Enum(*ETATS_PUBLICATION, name="module_publication_state")
    visibilite = sa.Enum(*VISIBILITES, name="module_visibility")
    etat_publication.create(bind, checkfirst=True)
    visibilite.create(bind, checkfirst=True)

    op.add_column(
        "module",
        sa.Column(
            "publicationState",
            etat_publication,
            nullable=False,
            server_default="draft",
            comment="Cycle de publication du module au catalogue (draft, review, published, ...).",
        ),
    )
    op.add_column(
        "module",
        sa.Column(
            "visibility",
            visibilite,
            nullable=False,
            server_default="hidden",
            comment="Visibilité du module dans le catalogue (hidden, visible, restricted).",
        ),
    )

    op.create_table(
        "module_version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("moduleId", sa.UUID(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False, comment="Version semver (ex. 1.2.0)."),
        sa.Column("digest", sa.String(length=200), nullable=True, comment="Empreinte du paquet."),
        sa.Column("provenance", sa.String(length=500), nullable=True, comment="Origine du paquet."),
        sa.Column("licence", sa.String(length=100), nullable=True),
        sa.Column("compatibility", sa.JSON(), nullable=True),
        sa.Column("prerequisites", sa.JSON(), nullable=True),
        sa.Column("stateVersion", sa.Integer(), server_default="1", nullable=False),
        sa.Column("publishedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["moduleId"], ["module.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("moduleId", "version", name="uq_module_version_module_version"),
        comment="Versions d'un module du catalogue ; une version publiée est immuable.",
    )
    op.create_index(op.f("ix_module_version_moduleId"), "module_version", ["moduleId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_module_version_moduleId"), table_name="module_version")
    op.drop_table("module_version")
    op.drop_column("module", "visibility")
    op.drop_column("module", "publicationState")

    bind = op.get_bind()
    sa.Enum(name="module_visibility").drop(bind, checkfirst=True)
    sa.Enum(name="module_publication_state").drop(bind, checkfirst=True)
