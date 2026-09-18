"""pompe de distribution (referentiel CRUD, pas de declaration de vente)

Revision ID: a3c8f1d2e4b7
Revises: 139b3a1a96cb
Create Date: 2026-09-17 13:00:00.000000

Nouvelle entite Pump (Pompe) pour le module zylo_liquid, distincte de
l'Equipment de maintenance type="pompe" deja existant (non touche ici) :
sert de socle pour la future declaration de volume vendu par pompe/shift
(hors perimetre de cette migration, CRUD seul). Rattachee a une station
(immuable) et a une cuve (determine le produit vendu, pas de champ produit
separe) - champs valides avec le commanditaire (id/timestamps/stationId/
tankId/name/active uniquement).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3c8f1d2e4b7'
down_revision: Union[str, None] = '139b3a1a96cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zyloLiquidPump',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('createdAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updatedAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        comment='Pompe de distribution rattachee a une cuve (referentiel, sans logique de declaration de vente).',
    )
    op.create_index('ix_zlPump_stationId', 'zyloLiquidPump', ['stationId'])
    op.create_index('ix_zlPump_tankId', 'zyloLiquidPump', ['tankId'])


def downgrade() -> None:
    op.drop_table('zyloLiquidPump')
