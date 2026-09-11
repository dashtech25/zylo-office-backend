"""gps tracking truck stops

Revision ID: 00e30f42d09d
Revises: b7c4e9f21a03
Create Date: 2026-09-11

4 nouvelles tables uniquement (mission « tracking », étape 1) — additif,
aucune table existante touchée. Écrit à la main : `alembic revision
--autogenerate` mêle systématiquement à ce diff un bruit important de
renommage d'index sans rapport (dérive préexistante déjà observée sur les
migrations précédentes de cette mission), et cette fois un changement de
type non lié (zyloLiquidReconciliationRecord.counterpartId), jamais
inclus ici.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '00e30f42d09d'
down_revision: Union[str, None] = 'b7c4e9f21a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('zyloLiquidGpsIngestCredential',
    sa.Column('organizationId', sa.UUID(), nullable=False),
    sa.Column('secretToken', sa.String(length=100), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organizationId', name='uq_zlGpsIngestCredential_org'),
    comment="Secret d'ingestion GPS par organisation — valide l'endpoint webhook, jamais un accès utilisateur."
    )
    op.create_index(op.f('ix_zyloLiquidGpsIngestCredential_organizationId'), 'zyloLiquidGpsIngestCredential', ['organizationId'], unique=False)

    op.create_table('zyloLiquidGpsDevice',
    sa.Column('organizationId', sa.UUID(), nullable=False),
    sa.Column('truckId', sa.UUID(), nullable=True),
    sa.Column('deviceIdentifier', sa.String(length=50), nullable=False),
    sa.Column('label', sa.String(length=150), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['truckId'], ['zyloLiquidTruck.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organizationId', 'deviceIdentifier', name='uq_zlGpsDevice_org_identifier'),
    comment='Boîtier GPS — référentiel réseau, rattaché optionnellement à un camion.'
    )
    op.create_index(op.f('ix_zyloLiquidGpsDevice_organizationId'), 'zyloLiquidGpsDevice', ['organizationId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidGpsDevice_truckId'), 'zyloLiquidGpsDevice', ['truckId'], unique=False)

    op.create_table('zyloLiquidTruckStopEvent',
    sa.Column('truckId', sa.UUID(), nullable=False),
    sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('startAt', sa.DateTime(), nullable=False),
    sa.Column('endAt', sa.DateTime(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['truckId'], ['zyloLiquidTruck.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment="Arrêt détecté d'un camion — dérivé du flux de positions, jamais un second système de vérité."
    )
    op.create_index('ix_zlTruckStopEvent_truckId_startAt', 'zyloLiquidTruckStopEvent', ['truckId', 'startAt'], unique=False)
    op.create_index(op.f('ix_zyloLiquidTruckStopEvent_truckId'), 'zyloLiquidTruckStopEvent', ['truckId'], unique=False)

    op.create_table('zyloLiquidTruckPositionPing',
    sa.Column('gpsDeviceId', sa.UUID(), nullable=False),
    sa.Column('recordedAt', sa.DateTime(), nullable=False),
    sa.Column('receivedAt', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=True),
    sa.Column('accuracyMeters', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('speedKmh', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('rawPayload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['gpsDeviceId'], ['zyloLiquidGpsDevice.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment="Position GPS brute — append-only, jamais modifiée. L'état dérivé (trajet/arrêts) est calculé séparément."
    )
    op.create_index('ix_zlTruckPositionPing_gpsDeviceId_recordedAt', 'zyloLiquidTruckPositionPing', ['gpsDeviceId', 'recordedAt'], unique=False)
    op.create_index(op.f('ix_zyloLiquidTruckPositionPing_gpsDeviceId'), 'zyloLiquidTruckPositionPing', ['gpsDeviceId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zyloLiquidTruckPositionPing_gpsDeviceId'), table_name='zyloLiquidTruckPositionPing')
    op.drop_index('ix_zlTruckPositionPing_gpsDeviceId_recordedAt', table_name='zyloLiquidTruckPositionPing')
    op.drop_table('zyloLiquidTruckPositionPing')

    op.drop_index(op.f('ix_zyloLiquidTruckStopEvent_truckId'), table_name='zyloLiquidTruckStopEvent')
    op.drop_index('ix_zlTruckStopEvent_truckId_startAt', table_name='zyloLiquidTruckStopEvent')
    op.drop_table('zyloLiquidTruckStopEvent')

    op.drop_index(op.f('ix_zyloLiquidGpsDevice_truckId'), table_name='zyloLiquidGpsDevice')
    op.drop_index(op.f('ix_zyloLiquidGpsDevice_organizationId'), table_name='zyloLiquidGpsDevice')
    op.drop_table('zyloLiquidGpsDevice')

    op.drop_index(op.f('ix_zyloLiquidGpsIngestCredential_organizationId'), table_name='zyloLiquidGpsIngestCredential')
    op.drop_table('zyloLiquidGpsIngestCredential')
