"""price_history_network_default_currency

Revision ID: f1a2b3c4d5e7
Revises: 95e8bd6bf477
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e7'
down_revision: Union[str, None] = '95e8bd6bf477'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Élargit la contrainte : l'ancienne contrainte (fuelProductId, effectiveFrom)
    # est un sous-ensemble strict de la nouvelle (fuelProductId, currencyId,
    # effectiveFrom) — aucune ligne existante ne peut être en conflit, migration
    # additive sans perte de données (refonte-configuration-zylo-liquid.md, Phase 4 §1).
    op.drop_index('uq_zlPriceHistory_networkDefault_product_effectiveFrom', table_name='zyloLiquidPriceHistory')
    op.create_index(
        'uq_zlPriceHistory_networkDefault_product_effectiveFrom',
        'zyloLiquidPriceHistory',
        ['fuelProductId', 'currencyId', 'effectiveFrom'],
        unique=True,
        postgresql_where=sa.text('"stationId" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_zlPriceHistory_networkDefault_product_effectiveFrom', table_name='zyloLiquidPriceHistory')
    op.create_index(
        'uq_zlPriceHistory_networkDefault_product_effectiveFrom',
        'zyloLiquidPriceHistory',
        ['fuelProductId', 'effectiveFrom'],
        unique=True,
        postgresql_where=sa.text('"stationId" IS NULL'),
    )
