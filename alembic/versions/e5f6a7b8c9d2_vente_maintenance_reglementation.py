"""vente_maintenance_reglementation

Revision ID: e5f6a7b8c9d2
Revises: d4e5f6a7b8c1
Create Date: 2026-09-07 00:00:00.000000

Mission « vente-maintenant-reglementation » — migration additive et
réversible (09-migration-donnees-et-deploiement.md de la mission) :
- Bloc 1 : colonnes additives sur zyloLiquidDocument.
- Bloc 3 : élargissement de zyloLiquidSale.paymentMethod (mobile money).
- Bloc 4 corrigé : nouvelles tables ProductSaleTransaction/ProductSaleLine,
  colonne additive nullable sur zyloLiquidReceivable (jamais de migration de
  la colonne saleId existante).
- Bloc 5 : zyloLiquidSellableProduct.
- Bloc 6 : zyloLiquidTechnician/Equipment/Intervention.
- Bloc 7 : zyloLiquidRegulatoryDocument/RegulatoryDeclaration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5f6a7b8c9d2'
down_revision: Union[str, None] = 'd4e5f6a7b8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Bloc 1 : extensions documentaires (additif, sans réécriture de table) ----
    op.add_column('zyloLiquidDocument', sa.Column('sensitivityLevel', sa.String(length=20), nullable=False, server_default='normal'))
    op.add_column('zyloLiquidDocument', sa.Column('supersedesDocumentId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDocument.id', ondelete='SET NULL'), nullable=True))
    op.add_column('zyloLiquidDocument', sa.Column('deletedAt', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint('ck_zlDocument_sensitivityLevel', 'zyloLiquidDocument', "\"sensitivityLevel\" IN ('normal','restreint')")

    # ---- Bloc 3 : modes de paiement carburant élargis (additif) ----
    op.alter_column('zyloLiquidSale', 'paymentMethod', type_=sa.String(length=20))
    op.drop_constraint('ck_zlSale_paymentMethod', 'zyloLiquidSale', type_='check')
    op.create_check_constraint(
        'ck_zlSale_paymentMethod', 'zyloLiquidSale',
        "\"paymentMethod\" IN ('cash','card','fleet','credit','orange_money','mtn_momo','bank_transfer','cheque','other')",
    )

    # ---- Bloc 5 : catalogue de produits vendables ----
    op.create_table(
        'zyloLiquidSellableProduct',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('sku', sa.String(length=60), nullable=True),
        sa.Column('barcodeValue', sa.String(length=64), nullable=True),
        sa.Column('category', sa.String(length=60), nullable=True),
        sa.Column('unitPriceAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('organizationId', 'barcodeValue', name='uq_zlSellableProduct_org_barcode'),
    )
    op.create_index('ix_zlSellableProduct_organizationId', 'zyloLiquidSellableProduct', ['organizationId'])
    op.create_index('ix_zlSellableProduct_stationId', 'zyloLiquidSellableProduct', ['stationId'])

    # ---- Bloc 4 corrigé : ventes boutique (paniers) ----
    op.create_table(
        'zyloLiquidProductSaleTransaction',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('authorUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('eventAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('currencyId', postgresql.UUID(as_uuid=True), sa.ForeignKey('currency.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('paymentMethod', sa.String(length=20), nullable=False),
        sa.Column('totalAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='completed'),
        sa.Column('commercialAccountId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidCommercialAccount.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('cancelledAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelledByUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "\"paymentMethod\" IN ('cash','card','orange_money','mtn_momo','bank_transfer','cheque','credit','other')",
            name='ck_zlProductSaleTransaction_paymentMethod',
        ),
        sa.CheckConstraint("status IN ('completed','cancelled')", name='ck_zlProductSaleTransaction_status'),
    )
    op.create_index('ix_zlProductSaleTransaction_stationId', 'zyloLiquidProductSaleTransaction', ['stationId'])
    op.create_index('ix_zlProductSaleTransaction_eventAt', 'zyloLiquidProductSaleTransaction', ['eventAt'])

    op.create_table(
        'zyloLiquidProductSaleLine',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('transactionId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidProductSaleTransaction.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sellableProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidSellableProduct.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 4), nullable=False),
        sa.Column('unitPriceAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('lineTotalAmount', sa.Numeric(14, 4), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_zlProductSaleLine_transactionId', 'zyloLiquidProductSaleLine', ['transactionId'])

    # ---- Receivable : origine boutique (colonne additive nullable, saleId assoupli) ----
    op.alter_column('zyloLiquidReceivable', 'saleId', nullable=True)
    op.add_column('zyloLiquidReceivable', sa.Column('productSaleTransactionId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidProductSaleTransaction.id', ondelete='RESTRICT'), nullable=True))
    op.create_index('ix_zlReceivable_productSaleTransactionId', 'zyloLiquidReceivable', ['productSaleTransactionId'])
    op.create_check_constraint(
        'ck_zlReceivable_exactly_one_origin', 'zyloLiquidReceivable',
        "(\"saleId\" IS NOT NULL)::int + (\"productSaleTransactionId\" IS NOT NULL)::int = 1",
    )

    # ---- Bloc 6 : Maintenance ----
    op.create_table(
        'zyloLiquidTechnician',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('company', sa.String(length=200), nullable=True),
        sa.Column('contact', sa.String(length=200), nullable=True),
        sa.Column('linkedUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_zlTechnician_organizationId', 'zyloLiquidTechnician', ['organizationId'])

    op.create_table(
        'zyloLiquidEquipment',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('type', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('manufacturer', sa.String(length=200), nullable=True),
        sa.Column('model', sa.String(length=200), nullable=True),
        sa.Column('serialNumber', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='in_service'),
        sa.Column('installedAt', sa.Date(), nullable=True),
        sa.Column('warrantyUntil', sa.Date(), nullable=True),
        sa.Column('lastMaintenanceAt', sa.Date(), nullable=True),
        sa.Column('nextMaintenanceDueAt', sa.Date(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('in_service','out_of_order','out_of_service')", name='ck_zlEquipment_status'),
    )
    op.create_index('ix_zlEquipment_stationId', 'zyloLiquidEquipment', ['stationId'])

    op.create_table(
        'zyloLiquidIntervention',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('equipmentId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidEquipment.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('technicianId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTechnician.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='planned'),
        sa.Column('openedAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('plannedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cost', sa.Numeric(14, 4), nullable=True),
        sa.Column('diagnosis', sa.Text(), nullable=True),
        sa.Column('actionTaken', sa.Text(), nullable=True),
        sa.Column('linkedAlertId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidAlert.id', ondelete='SET NULL'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("priority IN ('critical','high','medium','low')", name='ck_zlIntervention_priority'),
        sa.CheckConstraint("type IN ('preventive','corrective')", name='ck_zlIntervention_type'),
        sa.CheckConstraint("status IN ('planned','in_progress','closed')", name='ck_zlIntervention_status'),
    )
    op.create_index('ix_zlIntervention_equipmentId', 'zyloLiquidIntervention', ['equipmentId'])
    op.create_index('ix_zlIntervention_stationId', 'zyloLiquidIntervention', ['stationId'])
    op.create_index('ix_zlIntervention_openedAt', 'zyloLiquidIntervention', ['openedAt'])

    # ---- Bloc 7 : Réglementation ----
    op.create_table(
        'zyloLiquidRegulatoryDocument',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('documentType', sa.String(length=80), nullable=False),
        sa.Column('authority', sa.String(length=200), nullable=True),
        sa.Column('issuedAt', sa.Date(), nullable=True),
        sa.Column('expiresAt', sa.Date(), nullable=True),
        sa.Column('sourceReference', sa.Text(), nullable=True),
        sa.Column('certaintyLevel', sa.String(length=10), nullable=False, server_default='medium'),
        sa.Column('supersededByDocumentId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidRegulatoryDocument.id', ondelete='SET NULL'), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("\"certaintyLevel\" IN ('high','medium','low')", name='ck_zlRegulatoryDocument_certaintyLevel'),
    )
    op.create_index('ix_zlRegulatoryDocument_stationId', 'zyloLiquidRegulatoryDocument', ['stationId'])
    op.create_index('ix_zlRegulatoryDocument_expiresAt', 'zyloLiquidRegulatoryDocument', ['expiresAt'])

    op.create_table(
        'zyloLiquidRegulatoryDeclaration',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidStation.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('type', sa.String(length=80), nullable=False),
        sa.Column('authority', sa.String(length=200), nullable=True),
        sa.Column('triggerIncidentId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidIncidentDeclaration.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='to_produce'),
        sa.Column('reserve', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('to_produce','produced')", name='ck_zlRegulatoryDeclaration_status'),
    )
    op.create_index('ix_zlRegulatoryDeclaration_stationId', 'zyloLiquidRegulatoryDeclaration', ['stationId'])


def downgrade() -> None:
    op.drop_table('zyloLiquidRegulatoryDeclaration')
    op.drop_table('zyloLiquidRegulatoryDocument')
    op.drop_table('zyloLiquidIntervention')
    op.drop_table('zyloLiquidEquipment')
    op.drop_table('zyloLiquidTechnician')
    op.drop_constraint('ck_zlReceivable_exactly_one_origin', 'zyloLiquidReceivable', type_='check')
    op.drop_index('ix_zlReceivable_productSaleTransactionId', table_name='zyloLiquidReceivable')
    op.drop_column('zyloLiquidReceivable', 'productSaleTransactionId')
    op.alter_column('zyloLiquidReceivable', 'saleId', nullable=False)
    op.drop_table('zyloLiquidProductSaleLine')
    op.drop_table('zyloLiquidProductSaleTransaction')
    op.drop_table('zyloLiquidSellableProduct')
    op.drop_constraint('ck_zlSale_paymentMethod', 'zyloLiquidSale', type_='check')
    op.create_check_constraint('ck_zlSale_paymentMethod', 'zyloLiquidSale', "\"paymentMethod\" IN ('cash','card','fleet','credit')")
    op.alter_column('zyloLiquidSale', 'paymentMethod', type_=sa.String(length=10))
    op.drop_constraint('ck_zlDocument_sensitivityLevel', 'zyloLiquidDocument', type_='check')
    op.drop_column('zyloLiquidDocument', 'deletedAt')
    op.drop_column('zyloLiquidDocument', 'supersedesDocumentId')
    op.drop_column('zyloLiquidDocument', 'sensitivityLevel')
