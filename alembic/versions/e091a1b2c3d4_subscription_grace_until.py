"""BE-091 : colonne `subscription.graceUntil` (fin de la période de grâce).

Revision ID: e091a1b2c3d4
Revises: 089d4c7e2a10
Create Date: 2026-11-05 20:00:00.000000

Colonne nullable : elle reste vide tant que la durée de grâce n'est pas décidée (QE-FAC-07).
Aucun code de BE-091 ne la renseigne ni ne s'appuie dessus pour suspendre un abonnement.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e091a1b2c3d4'
down_revision: Union[str, None] = '089d4c7e2a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'subscription',
        sa.Column('graceUntil', sa.DateTime(timezone=True), nullable=True, comment="Fin de la période de grâce de l'incident (BE-091, NON DÉFINI : QE-FAC-07)."),
    )


def downgrade() -> None:
    op.drop_column('subscription', 'graceUntil')
