"""station admin center: security equipment, station supplier, financial fields

Centre administratif et opérationnel de la station — domaines Sécurité
(SecurityEquipment), Fournisseurs par station (StationSupplier) et Finances
(colonnes additives sur Station, `bankAccountInfo` gardé derrière
STATION_FINANCIAL_READ côté application, jamais dans le StationResponse
standard). Tout additif, non destructif.

Revision ID: 91faf138b6e2
Revises: d154543451d3
Create Date: 2026-09-08 08:38:48.205554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '91faf138b6e2'
down_revision: Union[str, None] = 'd154543451d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zyloLiquidSecurityEquipment',
        sa.Column('stationId', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('label', sa.String(length=150), nullable=False),
        sa.Column('lastControlAt', sa.Date(), nullable=True),
        sa.Column('nextControlDueAt', sa.Date(), nullable=True),
        sa.Column('conformityStatus', sa.String(length=20), server_default='a_controler', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("category IN ('extincteur','systeme_incendie','arret_urgence','point_evacuation','zone_atex','autre')", name='ck_zlSecurityEquipment_category'),
        sa.CheckConstraint('"conformityStatus" IN (\'conforme\',\'non_conforme\',\'a_controler\')', name='ck_zlSecurityEquipment_conformityStatus'),
        sa.ForeignKeyConstraint(['stationId'], ['zyloLiquidStation.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        comment="Équipement de sécurité incendie / zone ATEX d'une station, avec suivi de contrôle périodique.",
    )
    op.create_index(op.f('ix_zyloLiquidSecurityEquipment_stationId'), 'zyloLiquidSecurityEquipment', ['stationId'], unique=False)

    op.create_table(
        'zyloLiquidStationSupplier',
        sa.Column('stationId', sa.UUID(), nullable=False),
        sa.Column('supplierId', sa.UUID(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['stationId'], ['zyloLiquidStation.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supplierId'], ['zyloLiquidSupplier.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stationId', 'supplierId', name='uq_zlStationSupplier_station_supplier'),
        comment='Association explicite station <-> fournisseur du référentiel réseau.',
    )
    op.create_index(op.f('ix_zyloLiquidStationSupplier_stationId'), 'zyloLiquidStationSupplier', ['stationId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidStationSupplier_supplierId'), 'zyloLiquidStationSupplier', ['supplierId'], unique=False)

    op.add_column('zyloLiquidStation', sa.Column('taxId', sa.String(length=50), nullable=True))
    op.add_column('zyloLiquidStation', sa.Column('billingAddress', sa.Text(), nullable=True))
    op.add_column('zyloLiquidStation', sa.Column('costCenterCode', sa.String(length=50), nullable=True))
    op.add_column('zyloLiquidStation', sa.Column('bankAccountInfo', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('zyloLiquidStation', 'bankAccountInfo')
    op.drop_column('zyloLiquidStation', 'costCenterCode')
    op.drop_column('zyloLiquidStation', 'billingAddress')
    op.drop_column('zyloLiquidStation', 'taxId')

    op.drop_index(op.f('ix_zyloLiquidStationSupplier_supplierId'), table_name='zyloLiquidStationSupplier')
    op.drop_index(op.f('ix_zyloLiquidStationSupplier_stationId'), table_name='zyloLiquidStationSupplier')
    op.drop_table('zyloLiquidStationSupplier')

    op.drop_index(op.f('ix_zyloLiquidSecurityEquipment_stationId'), table_name='zyloLiquidSecurityEquipment')
    op.drop_table('zyloLiquidSecurityEquipment')
