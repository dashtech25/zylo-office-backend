"""country_currency_fk

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('country', sa.Column('currencyId', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_country_currencyId_currency',
        'country', 'currency',
        ['currencyId'], ['id'],
        ondelete='RESTRICT',
    )
    # Backfill mécanique et déterministe : relie chaque pays à la devise
    # dont le code correspond exactement à son `currencyCode` actuel
    # (jamais une correspondance devinée) — audit Configuration carburant
    # P1 §E.5. Les pays dont le `currencyCode` ne correspond à aucune
    # `Currency` existante gardent `currencyId` NULL plutôt qu'une valeur
    # inventée (la résolution applicative garde alors son repli sur
    # `currencyCode` en texte).
    op.execute(
        """
        UPDATE country
        SET "currencyId" = currency.id
        FROM currency
        WHERE country."currencyCode" = currency.code
        """
    )


def downgrade() -> None:
    op.drop_constraint('fk_country_currencyId_currency', 'country', type_='foreignkey')
    op.drop_column('country', 'currencyId')
