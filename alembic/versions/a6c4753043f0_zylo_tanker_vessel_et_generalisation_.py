"""zylo_tanker vessel et generalisation tracking gps camion/navire

Revision ID: a6c4753043f0
Revises: 9485538b2c45
Create Date: 2026-09-16

Généralise le tracking GPS (`app/location/`) et les alertes
(`app/alerts/`), jusqu'ici scopés camion uniquement, pour qu'un deuxième
type de véhicule (navire, module Zylo Tanker) puisse les utiliser sans
dupliquer l'algorithme de détection d'arrêt ni le schéma — voir le plan de
mission et la docstring de `app/location/models.py`.

Écrit à la main (même raison que les deux migrations précédentes du
tracking : l'autogenerate sur cette base mêle systématiquement un bruit
de renommage d'index/de type sans rapport avec le changement réel —
constaté en lançant `alembic revision --autogenerate` pour ce chantier,
des centaines de lignes de renommages d'index préexistants et non liés).

Contenu :
- Nouvelle table `zyloTankerVessel` (référentiel minimal navire).
- `zyloLiquidGpsDevice` : nouvelle colonne `vesselId` nullable (FK vers
  `zyloTankerVessel.id`, ON DELETE SET NULL) + contrainte CHECK
  interdisant `truckId` ET `vesselId` en même temps.
- `zyloLiquidGpsDeviceAssignment` : `truckId` devient nullable, nouvelle
  colonne `vesselId` nullable (FK, ON DELETE CASCADE) + contrainte CHECK
  exigeant exactement l'un des deux.
- `zyloLiquidTruckStopEvent` : `truckId` devient nullable, nouvelle
  colonne `vesselId` nullable (FK, ON DELETE RESTRICT) + contrainte CHECK
  exigeant exactement l'un des deux + index symétrique sur (vesselId,
  startAt).
- `zyloLiquidAlert` : nouvelle colonne `vesselId` nullable (FK, ON DELETE
  CASCADE) ; la contrainte CHECK `ck_zlAlert_station_or_truck` est
  remplacée par `ck_zlAlert_station_or_truck_or_vessel` (au moins un des
  trois renseigné).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a6c4753043f0'
down_revision: Union[str, None] = '9485538b2c45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Vessel (référentiel minimal, module zylo_tanker) ---
    op.create_table(
        'zyloTankerVessel',
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False, comment="Immatriculation/code d'identification du navire — unique par organisation."),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organizationId', 'code', name='uq_ztVessel_org_code'),
        comment='Bateau-citerne du réseau — référentiel minimal, cible de FK pour le tracking GPS généralisé.',
    )
    op.create_index(op.f('ix_zyloTankerVessel_organizationId'), 'zyloTankerVessel', ['organizationId'], unique=False)

    # --- GpsDevice : vesselId + CHECK ---
    op.add_column('zyloLiquidGpsDevice', sa.Column('vesselId', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_zyloLiquidGpsDevice_vesselId'), 'zyloLiquidGpsDevice', ['vesselId'], unique=False)
    op.create_foreign_key('zyloLiquidGpsDevice_vesselId_fkey', 'zyloLiquidGpsDevice', 'zyloTankerVessel', ['vesselId'], ['id'], ondelete='SET NULL')
    op.create_check_constraint(
        'ck_zlGpsDevice_truck_or_vessel',
        'zyloLiquidGpsDevice',
        'NOT ("truckId" IS NOT NULL AND "vesselId" IS NOT NULL)',
    )

    # --- GpsDeviceAssignment : truckId devient nullable, vesselId + CHECK ---
    op.alter_column('zyloLiquidGpsDeviceAssignment', 'truckId', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column('zyloLiquidGpsDeviceAssignment', sa.Column('vesselId', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_zlGpsDeviceAssignment_vesselId_assignedAt', 'zyloLiquidGpsDeviceAssignment', ['vesselId', 'assignedAt'], unique=False)
    op.create_index(op.f('ix_zyloLiquidGpsDeviceAssignment_vesselId'), 'zyloLiquidGpsDeviceAssignment', ['vesselId'], unique=False)
    op.create_foreign_key('zyloLiquidGpsDeviceAssignment_vesselId_fkey', 'zyloLiquidGpsDeviceAssignment', 'zyloTankerVessel', ['vesselId'], ['id'], ondelete='CASCADE')
    op.create_check_constraint(
        'ck_zlGpsDeviceAssignment_truck_xor_vessel',
        'zyloLiquidGpsDeviceAssignment',
        '(("truckId" IS NOT NULL)::int + ("vesselId" IS NOT NULL)::int) = 1',
    )

    # --- TruckStopEvent : truckId devient nullable, vesselId + CHECK + index ---
    op.alter_column('zyloLiquidTruckStopEvent', 'truckId', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column('zyloLiquidTruckStopEvent', sa.Column('vesselId', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_zlTruckStopEvent_vesselId_startAt', 'zyloLiquidTruckStopEvent', ['vesselId', 'startAt'], unique=False)
    op.create_index(op.f('ix_zyloLiquidTruckStopEvent_vesselId'), 'zyloLiquidTruckStopEvent', ['vesselId'], unique=False)
    op.create_foreign_key('zyloLiquidTruckStopEvent_vesselId_fkey', 'zyloLiquidTruckStopEvent', 'zyloTankerVessel', ['vesselId'], ['id'], ondelete='RESTRICT')
    op.create_check_constraint(
        'ck_zlTruckStopEvent_truck_xor_vessel',
        'zyloLiquidTruckStopEvent',
        '(("truckId" IS NOT NULL)::int + ("vesselId" IS NOT NULL)::int) = 1',
    )

    # --- Alert : vesselId + CHECK élargie ---
    op.add_column('zyloLiquidAlert', sa.Column('vesselId', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_zyloLiquidAlert_vesselId'), 'zyloLiquidAlert', ['vesselId'], unique=False)
    op.create_foreign_key('zyloLiquidAlert_vesselId_fkey', 'zyloLiquidAlert', 'zyloTankerVessel', ['vesselId'], ['id'], ondelete='CASCADE')
    op.drop_constraint('ck_zlAlert_station_or_truck', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint(
        'ck_zlAlert_station_or_truck_or_vessel',
        'zyloLiquidAlert',
        '"stationId" IS NOT NULL OR "truckId" IS NOT NULL OR "vesselId" IS NOT NULL',
    )


def downgrade() -> None:
    op.drop_constraint('ck_zlAlert_station_or_truck_or_vessel', 'zyloLiquidAlert', type_='check')
    op.create_check_constraint(
        'ck_zlAlert_station_or_truck',
        'zyloLiquidAlert',
        '"stationId" IS NOT NULL OR "truckId" IS NOT NULL',
    )
    op.drop_constraint('zyloLiquidAlert_vesselId_fkey', 'zyloLiquidAlert', type_='foreignkey')
    op.drop_index(op.f('ix_zyloLiquidAlert_vesselId'), table_name='zyloLiquidAlert')
    op.drop_column('zyloLiquidAlert', 'vesselId')

    op.drop_constraint('ck_zlTruckStopEvent_truck_xor_vessel', 'zyloLiquidTruckStopEvent', type_='check')
    op.drop_constraint('zyloLiquidTruckStopEvent_vesselId_fkey', 'zyloLiquidTruckStopEvent', type_='foreignkey')
    op.drop_index(op.f('ix_zyloLiquidTruckStopEvent_vesselId'), table_name='zyloLiquidTruckStopEvent')
    op.drop_index('ix_zlTruckStopEvent_vesselId_startAt', table_name='zyloLiquidTruckStopEvent')
    op.drop_column('zyloLiquidTruckStopEvent', 'vesselId')
    op.alter_column('zyloLiquidTruckStopEvent', 'truckId', existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_constraint('ck_zlGpsDeviceAssignment_truck_xor_vessel', 'zyloLiquidGpsDeviceAssignment', type_='check')
    op.drop_constraint('zyloLiquidGpsDeviceAssignment_vesselId_fkey', 'zyloLiquidGpsDeviceAssignment', type_='foreignkey')
    op.drop_index(op.f('ix_zyloLiquidGpsDeviceAssignment_vesselId'), table_name='zyloLiquidGpsDeviceAssignment')
    op.drop_index('ix_zlGpsDeviceAssignment_vesselId_assignedAt', table_name='zyloLiquidGpsDeviceAssignment')
    op.drop_column('zyloLiquidGpsDeviceAssignment', 'vesselId')
    op.alter_column('zyloLiquidGpsDeviceAssignment', 'truckId', existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_constraint('ck_zlGpsDevice_truck_or_vessel', 'zyloLiquidGpsDevice', type_='check')
    op.drop_constraint('zyloLiquidGpsDevice_vesselId_fkey', 'zyloLiquidGpsDevice', type_='foreignkey')
    op.drop_index(op.f('ix_zyloLiquidGpsDevice_vesselId'), table_name='zyloLiquidGpsDevice')
    op.drop_column('zyloLiquidGpsDevice', 'vesselId')

    op.drop_index(op.f('ix_zyloTankerVessel_organizationId'), table_name='zyloTankerVessel')
    op.drop_table('zyloTankerVessel')
