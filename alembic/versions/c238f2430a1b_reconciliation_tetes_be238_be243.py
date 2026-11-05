"""réconciliation des têtes BE-238 (fusion) et BE-243 (develop)

Revision ID: c238f2430a1b
Revises: adce56acf5ff, f243a0b1c2d4
Create Date: 2026-11-05 18:00:00.000000

Révision de fusion sans changement de schéma : elle joint les deux têtes
présentes après la fusion de be-238-v2 dans develop (adce56acf5ff, branche
BE-238 réconciliée) et f243a0b1c2d4 (tête de develop issue de BE-243).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c238f2430a1b'
down_revision: Union[str, None] = ('adce56acf5ff', 'f243a0b1c2d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aucun changement de schéma : révision de fusion des têtes."""
    pass


def downgrade() -> None:
    """Aucun changement de schéma à annuler : révision de fusion des têtes."""
    pass
