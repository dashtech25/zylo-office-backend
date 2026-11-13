"""BE-204 : table billing_invoice pour les factures génériques

Revision ID: be204001
Revises: <HEAD>
Create Date: 2026-11-12

Nouvelle table `billing_invoice` pour le domaine documents financiers (BE-204).
- Isolation tenant via tenantId (FK organization.id)
- Cycle de vie : draft | finalized | void (immuable après émission)
- Unicité (issuer, number) sauf quand number IS NULL
- Snapshot JSON pour données figées à la finalisation
- Verrou optimiste (version)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'be204001'
down_revision: Union[str, None] = '90f0db41ebb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Créer la table billing_invoice pour BE-204."""
    op.create_table(
        'billing_invoice',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('tenantId', sa.UUID(), nullable=False, comment='Tenant propriétaire (isolation, CA-3).'),
        sa.Column('payerId', sa.UUID(), nullable=False, comment='Entité à facturer (peut être différente du tenant).'),
        sa.Column('issuer', sa.String(length=255), nullable=False, comment='Nom/identifiant de l\'émetteur.'),
        sa.Column('number', sa.String(length=50), nullable=True, comment='Numéro de facture, NULL avant finalisation.'),
        sa.Column('state', sa.String(length=20), nullable=False, server_default='draft',
                  comment='État : draft | finalized | void (immuable après émission, CA-1).'),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='Données figées à la finalisation.'),
        sa.Column('issuedAt', sa.DateTime(timezone=True), nullable=False,
                  comment='Date d\'émission de la facture.'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1',
                  comment='Verrou optimiste (BE-072).'),
        sa.ForeignKeyConstraint(['tenantId'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('issuer', 'number', name='uq_billing_invoice_issuer_number',
                           comment='Unicité du numéro par émetteur (NULL exclu de l\'unicité).'),
        comment='Facture émise pour un tenant (BE-204), documents financiers.',
    )
    op.create_index('ix_billing_invoice_tenant_id', 'billing_invoice', ['tenantId'])
    op.create_index('ix_billing_invoice_payer_id', 'billing_invoice', ['payerId'])


def downgrade() -> None:
    """Supprimer la table billing_invoice."""
    op.drop_index('ix_billing_invoice_payer_id', table_name='billing_invoice')
    op.drop_index('ix_billing_invoice_tenant_id', table_name='billing_invoice')
    op.drop_table('billing_invoice')
