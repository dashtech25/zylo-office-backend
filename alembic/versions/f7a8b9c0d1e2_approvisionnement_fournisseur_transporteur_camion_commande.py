"""approvisionnement layer: supplier, carrier, truck, purchase order

Couche Approvisionnement (fusion prototype #/livraisons avec la couche
réelle) — 4 référentiels réseau + raccordement des déclarations de
livraison aux nouvelles entités (colonnes additives, toutes NULLables :
les lignes antérieures restent valides, le rapprochement Phase 6 n'en
dépend pas).

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d2
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e5f6a7b8c9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return [
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'zyloLiquidSupplier',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('type', sa.String(length=60), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index('ix_zlSupplier_organizationId', 'zyloLiquidSupplier', ['organizationId'])

    op.create_table(
        'zyloLiquidCarrier',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index('ix_zlCarrier_organizationId', 'zyloLiquidCarrier', ['organizationId'])

    op.create_table(
        'zyloLiquidTruck',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('carrierId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCarrier.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('plateNumber', sa.String(length=50), nullable=False),
        sa.Column('capacityLiters', sa.Numeric(12, 4), nullable=True),
        sa.Column('compartmentsCount', sa.SmallInteger(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint('organizationId', 'plateNumber', name='uq_zlTruck_org_plate'),
    )
    op.create_index('ix_zlTruck_organizationId', 'zyloLiquidTruck', ['organizationId'])
    op.create_index('ix_zlTruck_carrierId', 'zyloLiquidTruck', ['carrierId'])

    op.create_table(
        'zyloLiquidPurchaseOrder',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('supplierId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidSupplier.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('authorUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('orderReference', sa.String(length=100), nullable=False),
        sa.Column('orderedVolumeLiters', sa.Numeric(12, 4), nullable=False),
        sa.Column('orderedAt', sa.DateTime(), nullable=False),
        sa.Column('expectedAt', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='open'),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open','received')", name='ck_zlPurchaseOrder_status'),
        sa.CheckConstraint('"orderedVolumeLiters" > 0', name='ck_zlPurchaseOrder_orderedVolumeLiters_positive'),
    )
    op.create_index('ix_zlPurchaseOrder_stationId', 'zyloLiquidPurchaseOrder', ['stationId'])
    op.create_index('ix_zlPurchaseOrder_tankId', 'zyloLiquidPurchaseOrder', ['tankId'])
    op.create_index('ix_zlPurchaseOrder_supplierId', 'zyloLiquidPurchaseOrder', ['supplierId'])
    op.create_index('ix_zlPurchaseOrder_orderedAt', 'zyloLiquidPurchaseOrder', ['orderedAt'])

    op.add_column(
        'zyloLiquidDeliveryDeclaration',
        sa.Column('supplierId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidSupplier.id', ondelete='RESTRICT'), nullable=True),
    )
    op.add_column(
        'zyloLiquidDeliveryDeclaration',
        sa.Column('truckId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTruck.id', ondelete='RESTRICT'), nullable=True),
    )
    op.add_column(
        'zyloLiquidDeliveryDeclaration',
        sa.Column('purchaseOrderId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidPurchaseOrder.id', ondelete='RESTRICT'), nullable=True),
    )
    op.create_index('ix_zlDeliveryDeclaration_supplierId', 'zyloLiquidDeliveryDeclaration', ['supplierId'])
    op.create_index('ix_zlDeliveryDeclaration_truckId', 'zyloLiquidDeliveryDeclaration', ['truckId'])
    op.create_index('ix_zlDeliveryDeclaration_purchaseOrderId', 'zyloLiquidDeliveryDeclaration', ['purchaseOrderId'])


def downgrade() -> None:
    op.drop_index('ix_zlDeliveryDeclaration_purchaseOrderId', table_name='zyloLiquidDeliveryDeclaration')
    op.drop_index('ix_zlDeliveryDeclaration_truckId', table_name='zyloLiquidDeliveryDeclaration')
    op.drop_index('ix_zlDeliveryDeclaration_supplierId', table_name='zyloLiquidDeliveryDeclaration')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'purchaseOrderId')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'truckId')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'supplierId')

    op.drop_table('zyloLiquidPurchaseOrder')
    op.drop_table('zyloLiquidTruck')
    op.drop_table('zyloLiquidCarrier')
    op.drop_table('zyloLiquidSupplier')
