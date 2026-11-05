"""BE-058 : journal d'idempotence des événements de liaison facturation vers entitlements.

Crée la table `entitlement_source_events`. Une ligne par événement reçu sur
POST /api/v1/internal/billing/entitlement-events, unique sur `eventId`. Pas de clé
étrangère sur `organizationId` : une organisation inconnue doit pouvoir être journalisée
(CA-5). Pas de changement sur `subscription_entitlement` (`stateVersion` existe déjà, BE-045).

Revision ID: 058b1c2d3e4f
Revises: 3a2990daf8ef
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '058b1c2d3e4f'
down_revision: Union[str, None] = '3a2990daf8ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'entitlement_source_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('eventId', sa.String(length=160), nullable=False),
        sa.Column('eventType', sa.String(length=20), nullable=False),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscriptionId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entitlementId', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('subscription_entitlement.id'), nullable=True),
        sa.Column('outcome', sa.String(length=40), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('eventId', name='uq_entitlement_source_events_event_id'),
        sa.CheckConstraint("\"eventType\" IN ('granted', 'ended')", name='ck_entitlement_source_events_type'),
        comment="Journal d'idempotence des événements de liaison facturation vers entitlements (BE-058).",
    )
    op.create_index('ix_entitlement_source_events_organizationId', 'entitlement_source_events', ['organizationId'])


def downgrade() -> None:
    op.drop_index('ix_entitlement_source_events_organizationId', table_name='entitlement_source_events')
    op.drop_table('entitlement_source_events')
