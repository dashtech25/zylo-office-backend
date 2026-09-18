"""sale_pump_link

Revision ID: 84267b062f81
Revises: 036a585c6794
Create Date: 2026-09-18 00:00:00.000000

Ajout d'un lien optionnel Sale -> Pump (colonne additive nullable) pour
tracer une déclaration de vente jusqu'à la pompe d'origine, en vue du
futur rapprochement de stock par pompe. Réversible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '84267b062f81'
down_revision: Union[str, None] = '036a585c6794'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'zyloLiquidSale',
        sa.Column('pumpId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidPump.id', ondelete='RESTRICT'), nullable=True),
    )
    op.create_index('ix_zlSale_pumpId', 'zyloLiquidSale', ['pumpId'])


def downgrade() -> None:
    op.drop_index('ix_zlSale_pumpId', table_name='zyloLiquidSale')
    op.drop_column('zyloLiquidSale', 'pumpId')
