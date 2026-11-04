"""module.manifestVersion : version du contrat de manifeste du registre (BE-021)

Ajoute `module.manifestVersion` (entier, défaut 1). Une ligne dont la version n'est pas supportée
par le code (`VERSIONS_MANIFESTE_SUPPORTEES`) passe à l'état `incompatible` au lieu d'être lue.
Les lignes existantes reçoivent 1 par `server_default`, donc aucun module seedé n'est incompatible.

Revision ID: b60e229ba2de
Revises: e072b1c2d3a4
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b60e229ba2de'
down_revision: Union[str, None] = 'e072b1c2d3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'module',
        sa.Column(
            'manifestVersion',
            sa.Integer(),
            server_default='1',
            nullable=False,
            comment='Version du contrat de manifeste du module.',
        ),
    )


def downgrade() -> None:
    # Perte de la version de manifeste : sans elle, le code ne peut plus distinguer `incompatible`.
    op.drop_column('module', 'manifestVersion')
