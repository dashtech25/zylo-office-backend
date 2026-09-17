"""cuve choisie a la livraison, pas a la commande (refonte multi-lignes)

Revision ID: 139b3a1a96cb
Revises: 1047562d0691
Create Date: 2026-09-17 12:00:00.000000

Refonte validee scenario par scenario avec le commanditaire (2026-09-17) :
une commande d'approvisionnement ne vise plus une cuve unique, et une
declaration de livraison ne porte plus un produit/volume unique — chacune
devient une en-tete + plusieurs lignes, pour representer une visite de
camion qui peut toucher plusieurs cuves et/ou plusieurs produits. Les
donnees existantes (reelles, pas des fixtures) sont retro-migrees sans
perte avant que les anciennes colonnes ne soient supprimees.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '139b3a1a96cb'
down_revision: Union[str, None] = '1047562d0691'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Nouvelles tables --------------------------------------------
    op.create_table(
        'zyloLiquidPurchaseOrderLine',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('createdAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updatedAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('purchaseOrderId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidPurchaseOrder.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fuelProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidFuelProduct.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('orderedVolumeLiters', sa.Numeric(12, 4), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.CheckConstraint("status IN ('open','partially_received','received')", name='ck_zlPurchaseOrderLine_status'),
        sa.CheckConstraint('"orderedVolumeLiters" > 0', name='ck_zlPurchaseOrderLine_orderedVolumeLiters_positive'),
        comment='Un produit commande — le statut de la commande est agrege depuis ses lignes.',
    )
    op.create_index('ix_zlPurchaseOrderLine_purchaseOrderId', 'zyloLiquidPurchaseOrderLine', ['purchaseOrderId'])
    op.create_index('ix_zlPurchaseOrderLine_fuelProductId', 'zyloLiquidPurchaseOrderLine', ['fuelProductId'])

    op.create_table(
        'zyloLiquidDeliveryDeclarationLine',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('createdAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updatedAt', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('declarationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDeliveryDeclaration.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('purchaseOrderLineId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidPurchaseOrderLine.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('volumeLiters', sa.Numeric(12, 4), nullable=False),
        sa.Column('correctsLineId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDeliveryDeclarationLine.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reconciledWithType', sa.String(40), nullable=True),
        sa.CheckConstraint('"volumeLiters" > 0', name='ck_zlDeliveryDeclarationLine_volumeLiters_positive'),
        comment='Une cuve reellement remplie durant une visite de livraison.',
    )
    op.create_index('ix_zlDeliveryDeclarationLine_declarationId', 'zyloLiquidDeliveryDeclarationLine', ['declarationId'])
    op.create_index('ix_zlDeliveryDeclarationLine_tankId', 'zyloLiquidDeliveryDeclarationLine', ['tankId'])
    op.create_index('ix_zlDeliveryDeclarationLine_purchaseOrderLineId', 'zyloLiquidDeliveryDeclarationLine', ['purchaseOrderLineId'])

    # --- 2. Retro-migration des donnees existantes (reelles) ------------
    # Une ligne de commande par commande existante (mono-produit avant la
    # refonte) — le produit vient de la cuve visee (ancienne colonne
    # PurchaseOrder.tankId, supprimee plus bas). Statut copie tel quel :
    # seuls 'open'/'received' existaient avant (pas d'etat intermediaire).
    op.execute("""
        INSERT INTO "zyloLiquidPurchaseOrderLine" (id, "createdAt", "updatedAt", "purchaseOrderId", "fuelProductId", "orderedVolumeLiters", status)
        SELECT gen_random_uuid(), now(), now(), po.id, t."fuelProductId", po."orderedVolumeLiters", po.status
        FROM "zyloLiquidPurchaseOrder" po
        JOIN "zyloLiquidTank" t ON t.id = po."tankId"
    """)

    # Une ligne de declaration par declaration existante — la cuve vient de
    # la commande liee (ancienne colonne DeliveryDeclaration.purchaseOrderId,
    # supprimee plus bas) ; rattachee a la ligne de commande generee
    # ci-dessus pour ce meme couple commande+produit. Le rapprochement
    # (reconciledWithId/Type) migre de l'en-tete vers la ligne.
    op.execute("""
        INSERT INTO "zyloLiquidDeliveryDeclarationLine" (id, "createdAt", "updatedAt", "declarationId", "tankId", "purchaseOrderLineId", "volumeLiters", "reconciledWithId", "reconciledWithType")
        SELECT gen_random_uuid(), now(), now(), dd.id, po."tankId", pol.id, dd."declaredVolumeLiters", dd."reconciledWithId", dd."reconciledWithType"
        FROM "zyloLiquidDeliveryDeclaration" dd
        JOIN "zyloLiquidPurchaseOrder" po ON po.id = dd."purchaseOrderId"
        JOIN "zyloLiquidPurchaseOrderLine" pol ON pol."purchaseOrderId" = po.id
        WHERE dd."purchaseOrderId" IS NOT NULL
    """)

    # --- 3. Anciennes colonnes / contraintes ------------------------------
    op.drop_constraint('ck_zlPurchaseOrder_orderedVolumeLiters_positive', 'zyloLiquidPurchaseOrder', type_='check')
    op.drop_constraint('ck_zlPurchaseOrder_status', 'zyloLiquidPurchaseOrder', type_='check')
    op.drop_column('zyloLiquidPurchaseOrder', 'tankId')
    op.drop_column('zyloLiquidPurchaseOrder', 'orderedVolumeLiters')
    op.alter_column('zyloLiquidPurchaseOrder', 'status', type_=sa.String(20))
    op.create_check_constraint('ck_zlPurchaseOrder_status', 'zyloLiquidPurchaseOrder', "status IN ('open','partially_received','received')")

    op.drop_column('zyloLiquidDeliveryDeclaration', 'fuelProductId')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'declaredVolumeLiters')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'purchaseOrderId')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'reconciledWithId')
    op.drop_column('zyloLiquidDeliveryDeclaration', 'reconciledWithType')


def downgrade() -> None:
    op.add_column('zyloLiquidDeliveryDeclaration', sa.Column('reconciledWithType', sa.String(40), nullable=True))
    op.add_column('zyloLiquidDeliveryDeclaration', sa.Column('reconciledWithId', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('zyloLiquidDeliveryDeclaration', sa.Column('purchaseOrderId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidPurchaseOrder.id', ondelete='RESTRICT'), nullable=True))
    op.add_column('zyloLiquidDeliveryDeclaration', sa.Column('declaredVolumeLiters', sa.Numeric(12, 4), nullable=True))
    op.add_column('zyloLiquidDeliveryDeclaration', sa.Column('fuelProductId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidFuelProduct.id', ondelete='RESTRICT'), nullable=True))

    op.drop_constraint('ck_zlPurchaseOrder_status', 'zyloLiquidPurchaseOrder', type_='check')
    op.add_column('zyloLiquidPurchaseOrder', sa.Column('orderedVolumeLiters', sa.Numeric(12, 4), nullable=True))
    op.add_column('zyloLiquidPurchaseOrder', sa.Column('tankId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidTank.id', ondelete='RESTRICT'), nullable=True))
    op.create_check_constraint('ck_zlPurchaseOrder_status', 'zyloLiquidPurchaseOrder', "status IN ('open','received')")

    op.drop_table('zyloLiquidDeliveryDeclarationLine')
    op.drop_table('zyloLiquidPurchaseOrderLine')
