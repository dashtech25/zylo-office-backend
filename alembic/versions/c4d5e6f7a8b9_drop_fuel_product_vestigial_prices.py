"""drop_fuel_product_vestigial_prices

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # currentPriceFcfa/currentCostFcfa : dénormalisation FCFA de l'ancien
    # schéma, confirmée jamais lue ni écrite par aucun service (audit
    # Configuration carburant P1 §B) — PriceHistory est la seule source de
    # vérité pour un prix. Retirées plutôt que laissées comme un champ mort
    # trompeur dans l'API.
    op.drop_column('zyloLiquidFuelProduct', 'currentPriceFcfa')
    op.drop_column('zyloLiquidFuelProduct', 'currentCostFcfa')


def downgrade() -> None:
    op.add_column('zyloLiquidFuelProduct', sa.Column('currentCostFcfa', sa.Numeric(10, 2), nullable=True))
    op.add_column('zyloLiquidFuelProduct', sa.Column('currentPriceFcfa', sa.Numeric(10, 2), nullable=True))
