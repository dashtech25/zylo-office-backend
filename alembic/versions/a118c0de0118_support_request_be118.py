"""Table support_request : demandes de support client (BE-118)

Revision ID: a118c0de0118
Revises: c9d8e7f6a5b4
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a118c0de0118'
down_revision: Union[str, None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_request',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('statut', sa.String(length=20), server_default='open', nullable=False),
        sa.Column('contexte', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('createdBy', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('open', 'in_progress', 'resolved')", name='ck_support_request_statut'),
        comment='Demandes de support client par organisation, contexte non secret (BE-118).',
    )
    op.create_index(op.f('ix_support_request_organizationId'), 'support_request', ['organizationId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_support_request_organizationId'), table_name='support_request')
    op.drop_table('support_request')
