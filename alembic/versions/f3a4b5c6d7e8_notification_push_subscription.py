"""notifications: web push subscription table

Module Notifications (capacité partagée, core) — un seul canal pour
l'instant, Web Push navigateur (RFC 8030). Voir app/notifications/.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = '5b1c9e7d3a4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notificationPushSubscription',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('userId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dhKey', sa.String(length=255), nullable=False),
        sa.Column('authKey', sa.String(length=255), nullable=False),
        sa.Column('userAgent', sa.String(length=255), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('endpoint', name='uq_notificationPushSubscription_endpoint'),
        comment='Abonnement Web Push navigateur (RFC 8030) — module Notifications, 2026-09-20.',
    )
    op.create_index('ix_notificationPushSubscription_userId', 'notificationPushSubscription', ['userId'])
    op.create_index('ix_notificationPushSubscription_organizationId', 'notificationPushSubscription', ['organizationId'])


def downgrade() -> None:
    op.drop_index('ix_notificationPushSubscription_organizationId', table_name='notificationPushSubscription')
    op.drop_index('ix_notificationPushSubscription_userId', table_name='notificationPushSubscription')
    op.drop_table('notificationPushSubscription')
