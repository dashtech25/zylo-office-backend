"""BE-214 : tables retention_policy et legal_hold pour rétention/purge

Revision ID: be214001
Revises: a198f215
Create Date: 2026-11-12

Tables :
- retention_policy : durées de rétention par catégorie
- legal_hold : verrous légaux bloquant la purge

Rattachement (réconciliation develop) : enchaînée après a198f215 (fusion
BE-198/BE-215), la tête réelle de la chaîne BE-198→BE-203→BE-214 au moment de
la fusion de be-214-lot dans develop. Les têtes restantes sont unifiées par
la migration de fusion finale.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'be214001'
down_revision: Union[str, None] = 'a198f215'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Créer les tables retention_policy et legal_hold."""
    op.create_table(
        'retention_policy',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False, unique=True,
                  comment='Catégorie : audit, logs, exports, etc.'),
        sa.Column('duration_days', sa.Integer(), nullable=True,
                  comment='Durée de rétention en jours (NULL = non défini, aucune purge).'),
        sa.Column('description', sa.Text(), nullable=True,
                  comment='Description de la politique.'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        comment='Politique de rétention : catégories et durées (BE-214).',
    )
    op.create_index('ix_retention_policy_category', 'retention_policy', ['category'])

    op.create_table(
        'legal_hold',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('tenantId', sa.UUID(), nullable=False,
                  comment='Tenant/organisation verrouillée.'),
        sa.Column('scope', sa.String(length=50), nullable=False,
                  comment='Scope du verrou : tenant, organization, etc.'),
        sa.Column('setAt', sa.DateTime(timezone=True), nullable=False,
                  comment='Date de mise en place du verrou.'),
        sa.Column('releasedAt', sa.DateTime(timezone=True), nullable=True,
                  comment='Date de libération (NULL = actif, en cours).'),
        sa.Column('reason', sa.Text(), nullable=True,
                  comment='Motif du verrou.'),
        sa.ForeignKeyConstraint(['tenantId'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        comment='Verrou légal : bloque la purge jusqu\'à libération (BE-214).',
    )
    op.create_index('ix_legal_hold_tenant_id', 'legal_hold', ['tenantId'])
    op.create_index('ix_legal_hold_scope', 'legal_hold', ['scope'])


def downgrade() -> None:
    """Supprimer les tables legal_hold et retention_policy."""
    op.drop_index('ix_legal_hold_scope', table_name='legal_hold')
    op.drop_index('ix_legal_hold_tenant_id', table_name='legal_hold')
    op.drop_table('legal_hold')

    op.drop_index('ix_retention_policy_category', table_name='retention_policy')
    op.drop_table('retention_policy')
