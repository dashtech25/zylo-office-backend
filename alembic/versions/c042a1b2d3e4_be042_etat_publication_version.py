"""BE-042 : état de publication des versions de module.

Ajoute à `module_version` la colonne `publicationState` (enum PostgreSQL
`module_version_publication_state` : draft, review, published). Les lignes existantes reçoivent
`draft` ; celles qui portent déjà une `publishedAt` (écrites avant cette migration) passent à
`published`, pour rester cohérentes avec leur date de publication.

Downgrade : supprime la colonne puis l'enum. Aucune donnée métier n'est perdue, car l'état est
dérivable de `publishedAt` pour les versions publiées.

Revision ID: c042a1b2d3e4
Revises: f668520e8d62
Create Date: 2026-11-04 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c042a1b2d3e4"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ETATS_VERSION = ("draft", "review", "published")
NOM_ENUM = "module_version_publication_state"


def upgrade() -> None:
    bind = op.get_bind()
    etat = sa.Enum(*ETATS_VERSION, name=NOM_ENUM)
    etat.create(bind, checkfirst=True)
    op.add_column(
        "module_version",
        sa.Column(
            "publicationState",
            etat,
            nullable=False,
            server_default="draft",
            comment="État de publication de la version (draft, review, published).",
        ),
    )
    op.execute('UPDATE module_version SET "publicationState" = \'published\' WHERE "publishedAt" IS NOT NULL')


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_column("module_version", "publicationState")
    sa.Enum(*ETATS_VERSION, name=NOM_ENUM).drop(bind, checkfirst=True)
