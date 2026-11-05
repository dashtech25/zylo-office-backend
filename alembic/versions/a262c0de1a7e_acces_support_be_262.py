"""Table acces_support : accès support en lecture seule par défaut (BE-262)

Revision ID: a262c0de1a7e
Revises: fd57ba293e8b
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a262c0de1a7e'
down_revision: Union[str, None] = 'fd57ba293e8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'acces_support',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('supportUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('creeParUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('mode', sa.String(length=20), server_default='lecture', nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('debutUtc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finUtc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approbationId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment='Accès support à une organisation : lecture seule par défaut, justifié, daté (BE-262).',
    )
    op.create_index(op.f('ix_acces_support_organizationId'), 'acces_support', ['organizationId'], unique=False)
    op.create_index(op.f('ix_acces_support_supportUserId'), 'acces_support', ['supportUserId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_acces_support_supportUserId'), table_name='acces_support')
    op.drop_index(op.f('ix_acces_support_organizationId'), table_name='acces_support')
    op.drop_table('acces_support')
