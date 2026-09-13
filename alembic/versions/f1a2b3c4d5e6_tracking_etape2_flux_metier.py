"""tracking gps camions etape 2 - flux metier

Revision ID: f1a2b3c4d5e6
Revises: 9355a8709666
Create Date: 2026-09-12

Étape 2 du tracking GPS (flux métier — lieux nommés, historique boîtier
<->camion, réconciliation, commentaires, rattachement commande). 7
nouvelles tables + colonnes additives sur `zyloLiquidTruckStopEvent`
(locationId, reconciliationStatus) et `zyloLiquidAlert` (stationId
devient nullable, truckId ajouté, nouveau type). Écrit à la main (même
raison que la migration étape 1 : l'autogenerate sur cette base mêle
systématiquement un bruit de renommage d'index sans rapport)."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '9355a8709666'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('zyloLiquidGpsDeviceAssignment',
    sa.Column('gpsDeviceId', sa.UUID(), nullable=False),
    sa.Column('truckId', sa.UUID(), nullable=False),
    sa.Column('assignedAt', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('unassignedAt', sa.DateTime(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['gpsDeviceId'], ['zyloLiquidGpsDevice.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['truckId'], ['zyloLiquidTruck.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    comment="Historique des périodes d'association boîtier<->camion — jamais réécrit, une réaffectation ferme la ligne active et en ouvre une nouvelle."
    )
    op.create_index('ix_zlGpsDeviceAssignment_gpsDeviceId_assignedAt', 'zyloLiquidGpsDeviceAssignment', ['gpsDeviceId', 'assignedAt'], unique=False)
    op.create_index('ix_zlGpsDeviceAssignment_truckId_assignedAt', 'zyloLiquidGpsDeviceAssignment', ['truckId', 'assignedAt'], unique=False)
    op.create_index(op.f('ix_zyloLiquidGpsDeviceAssignment_gpsDeviceId'), 'zyloLiquidGpsDeviceAssignment', ['gpsDeviceId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidGpsDeviceAssignment_truckId'), 'zyloLiquidGpsDeviceAssignment', ['truckId'], unique=False)

    op.create_table('zyloLiquidTraccarConnection',
    sa.Column('organizationId', sa.UUID(), nullable=False),
    sa.Column('baseUrl', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('password', sa.String(length=255), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organizationId', name='uq_zlTraccarConnection_org'),
    comment='Identifiants de connexion à l\'API Traccar de l\'organisation — jamais exposés au navigateur.'
    )
    op.create_index(op.f('ix_zyloLiquidTraccarConnection_organizationId'), 'zyloLiquidTraccarConnection', ['organizationId'], unique=False)

    op.create_table('zyloLiquidTruckTrackingLocation',
    sa.Column('organizationId', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False, server_default='libre'),
    sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=False),
    sa.Column('radiusMeters', sa.Numeric(precision=8, scale=2), nullable=False, server_default='150'),
    sa.Column('status', sa.String(length=10), nullable=False, server_default='active'),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('port','entrepot','depot_fournisseur','libre')", name='ck_zlTruckTrackingLocation_type'),
    sa.CheckConstraint("status IN ('active','deleted')", name='ck_zlTruckTrackingLocation_status'),
    sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment="Lieu nommé de référence pour la reconnaissance automatique d'arrêt — jamais une géozone Traccar."
    )
    op.create_index(op.f('ix_zyloLiquidTruckTrackingLocation_organizationId'), 'zyloLiquidTruckTrackingLocation', ['organizationId'], unique=False)

    op.add_column('zyloLiquidTruckStopEvent', sa.Column('locationId', sa.UUID(), nullable=True))
    op.add_column('zyloLiquidTruckStopEvent', sa.Column('reconciliationStatus', sa.String(length=10), nullable=False, server_default='none'))
    op.create_foreign_key('fk_zlTruckStopEvent_locationId', 'zyloLiquidTruckStopEvent', 'zyloLiquidTruckTrackingLocation', ['locationId'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_zyloLiquidTruckStopEvent_locationId'), 'zyloLiquidTruckStopEvent', ['locationId'], unique=False)
    op.create_check_constraint('ck_zlTruckStopEvent_reconciliationStatus', 'zyloLiquidTruckStopEvent', "\"reconciliationStatus\" IN ('none','pending','resolved')")

    op.create_table('zyloLiquidTruckStopReconciliation',
    sa.Column('stopEventId', sa.UUID(), nullable=False),
    sa.Column('candidateLocationIds', postgresql.JSONB(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False, server_default='pending'),
    sa.Column('resolvedLocationId', sa.UUID(), nullable=True),
    sa.Column('resolvedByUserId', sa.UUID(), nullable=True),
    sa.Column('resolvedAt', sa.DateTime(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending','resolved')", name='ck_zlTruckStopReconciliation_status'),
    sa.ForeignKeyConstraint(['stopEventId'], ['zyloLiquidTruckStopEvent.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolvedLocationId'], ['zyloLiquidTruckTrackingLocation.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['resolvedByUserId'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stopEventId'),
    comment="File d'arrêts ambigus (chevauchement de lieux) en attente d'un arbitrage humain."
    )
    op.create_index(op.f('ix_zyloLiquidTruckStopReconciliation_stopEventId'), 'zyloLiquidTruckStopReconciliation', ['stopEventId'], unique=False)

    op.create_table('zyloLiquidTruckStopComment',
    sa.Column('stopEventId', sa.UUID(), nullable=False),
    sa.Column('authorUserId', sa.UUID(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['stopEventId'], ['zyloLiquidTruckStopEvent.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['authorUserId'], ['user.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment='Commentaire humain sur un arrêt de camion — modifiable/supprimable, plusieurs par arrêt.'
    )
    op.create_index(op.f('ix_zyloLiquidTruckStopComment_stopEventId'), 'zyloLiquidTruckStopComment', ['stopEventId'], unique=False)

    op.create_table('zyloLiquidTruckOrderAssignment',
    sa.Column('truckId', sa.UUID(), nullable=False),
    sa.Column('purchaseOrderId', sa.UUID(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['truckId'], ['zyloLiquidTruck.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['purchaseOrderId'], ['zyloLiquidPurchaseOrder.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('truckId', 'purchaseOrderId', name='uq_zlTruckOrderAssignment_truck_order'),
    comment='Lien plusieurs-à-plusieurs camion<->commande d\'approvisionnement, toujours optionnel.'
    )
    op.create_index(op.f('ix_zyloLiquidTruckOrderAssignment_truckId'), 'zyloLiquidTruckOrderAssignment', ['truckId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidTruckOrderAssignment_purchaseOrderId'), 'zyloLiquidTruckOrderAssignment', ['purchaseOrderId'], unique=False)

    op.create_table('zyloLiquidTrackingSettings',
    sa.Column('organizationId', sa.UUID(), nullable=False),
    sa.Column('stopStabilizationMinutes', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('stopRadiusMeters', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('liveViewThrottleMs', sa.SmallInteger(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organizationId', name='uq_zlTrackingSettings_org'),
    comment='Réglages de tracking par organisation — repli sur les constantes réseau si absent.'
    )
    op.create_index(op.f('ix_zyloLiquidTrackingSettings_organizationId'), 'zyloLiquidTrackingSettings', ['organizationId'], unique=False)

    # Alert : un camion n'est pas toujours rattaché à une station (arrêt
    # hors lieu connu) — stationId devient nullable, truckId ajouté,
    # nouveau type 'truck_stop_unqualified', et un CHECK garantit qu'au
    # moins l'un des deux reste renseigné (jamais une alerte orpheline).
    op.alter_column('zyloLiquidAlert', 'stationId', nullable=True)
    op.add_column('zyloLiquidAlert', sa.Column('truckId', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_zlAlert_truckId', 'zyloLiquidAlert', 'zyloLiquidTruck', ['truckId'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_zyloLiquidAlert_truckId'), 'zyloLiquidAlert', ['truckId'], unique=False)
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint(
        'ck_zlAlert_type', 'zyloLiquidAlert',
        "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
        "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
        "'price_missing','sensor_mapping_missing','calibration_missing','truck_stop_unqualified')",
    )
    op.create_check_constraint('ck_zlAlert_station_or_truck', 'zyloLiquidAlert', '"stationId" IS NOT NULL OR "truckId" IS NOT NULL')


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_station_or_truck', 'zyloLiquidAlert', type_='check')
    op.drop_constraint('ck_zlAlert_type', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint(
        'ck_zlAlert_type', 'zyloLiquidAlert',
        "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
        "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
        "'price_missing','sensor_mapping_missing','calibration_missing')",
    )
    op.drop_index(op.f('ix_zyloLiquidAlert_truckId'), table_name='zyloLiquidAlert')
    op.drop_constraint('fk_zlAlert_truckId', 'zyloLiquidAlert', type_='foreignkey')
    op.drop_column('zyloLiquidAlert', 'truckId')
    op.alter_column('zyloLiquidAlert', 'stationId', nullable=False)

    op.drop_table('zyloLiquidTrackingSettings')
    op.drop_table('zyloLiquidTruckOrderAssignment')
    op.drop_table('zyloLiquidTruckStopComment')
    op.drop_table('zyloLiquidTruckStopReconciliation')

    op.drop_constraint('ck_zlTruckStopEvent_reconciliationStatus', 'zyloLiquidTruckStopEvent', type_='check')
    op.drop_index(op.f('ix_zyloLiquidTruckStopEvent_locationId'), table_name='zyloLiquidTruckStopEvent')
    op.drop_constraint('fk_zlTruckStopEvent_locationId', 'zyloLiquidTruckStopEvent', type_='foreignkey')
    op.drop_column('zyloLiquidTruckStopEvent', 'reconciliationStatus')
    op.drop_column('zyloLiquidTruckStopEvent', 'locationId')

    op.drop_table('zyloLiquidTruckTrackingLocation')
    op.drop_table('zyloLiquidTraccarConnection')
    op.drop_table('zyloLiquidGpsDeviceAssignment')
