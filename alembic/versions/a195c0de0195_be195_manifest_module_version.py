"""module_version.manifest : manifeste de module validé (BE-195)

Ajoute `module_version.manifest` (JSON, nullable). Une version créée sans manifeste (BE-042)
garde NULL ; une version créée par la publication de manifeste (BE-195) porte le manifeste
validé. Aucune donnée existante n'est modifiée.

Revision ID: a195c0de0195
Revises: 24165cba1ba6
Create Date: 2026-11-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a195c0de0195'
down_revision: Union[str, None] = '24165cba1ba6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'module_version',
        sa.Column('manifest', sa.JSON(), nullable=True, comment='Manifeste de module validé à la publication (BE-195).'),
    )


def downgrade() -> None:
    # Perte du manifeste publié : les versions créées par BE-195 perdent leur contenu validé.
    op.drop_column('module_version', 'manifest')
