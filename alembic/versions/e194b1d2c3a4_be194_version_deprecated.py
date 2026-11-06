"""BE-194 : état `deprecated` pour les versions de module.

Ajoute la valeur `deprecated` à l'enum PostgreSQL `module_version_publication_state`
(colonne `module_version.publicationState`). Une version dépréciée reste publiée et lisible,
mais la lecture de cette version répond 422 et elle n'est jamais proposée à l'installation.

PostgreSQL ne sait pas retirer une valeur d'enum : le downgrade recrée le type sans `deprecated`.
Les versions dépréciées repassent alors à `published`, état le plus proche qui reste lisible.
Cette perte d'information (le fait qu'une version était dépréciée) est acceptée, car le downgrade
ne sert qu'à revenir en arrière pendant le développement.

Revision ID: e194b1d2c3a4
Revises: b189c0de0189
Create Date: 2026-11-06 00:00:00

"""

from typing import Sequence, Union

from alembic import op

revision: str = "e194b1d2c3a4"
down_revision: Union[str, None] = "b189c0de0189"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOM_ENUM = "module_version_publication_state"


def upgrade() -> None:
    # ADD VALUE est autorisé dans une transaction (PostgreSQL 12+) ; la valeur n'est lue qu'après.
    op.execute(f"ALTER TYPE {NOM_ENUM} ADD VALUE IF NOT EXISTS 'deprecated'")


def downgrade() -> None:
    op.execute("UPDATE module_version SET \"publicationState\" = 'published' WHERE \"publicationState\" = 'deprecated'")
    op.execute("ALTER TABLE module_version ALTER COLUMN \"publicationState\" DROP DEFAULT")
    op.execute(f"ALTER TYPE {NOM_ENUM} RENAME TO {NOM_ENUM}_avec_deprecated")
    op.execute(f"CREATE TYPE {NOM_ENUM} AS ENUM ('draft', 'review', 'published')")
    op.execute(
        f"ALTER TABLE module_version ALTER COLUMN \"publicationState\" TYPE {NOM_ENUM} "
        f"USING \"publicationState\"::text::{NOM_ENUM}"
    )
    op.execute(f"DROP TYPE {NOM_ENUM}_avec_deprecated")
    op.execute("ALTER TABLE module_version ALTER COLUMN \"publicationState\" SET DEFAULT 'draft'")
