"""document_layer_bloc5

Revision ID: c3d4e5f6a7b0
Revises: b2c3d4e5f6a9
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b0'
down_revision: Union[str, None] = 'b2c3d4e5f6a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zyloLiquidDocument',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('storageReference', sa.String(length=500), nullable=False),
        sa.Column('fileName', sa.String(length=255), nullable=False),
        sa.Column('mimeType', sa.String(length=100), nullable=True),
        sa.Column('uploadedByUserId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_zlDocument_organizationId', 'zyloLiquidDocument', ['organizationId'])

    op.create_table(
        'zyloLiquidDocumentLink',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('documentId', postgresql.UUID(as_uuid=True), sa.ForeignKey('zyloLiquidDocument.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('linkedEntityType', sa.String(length=40), nullable=False),
        sa.Column('linkedEntityId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('documentId', 'linkedEntityType', 'linkedEntityId', name='uq_zlDocumentLink_document_entity'),
    )
    op.create_index('ix_zlDocumentLink_documentId', 'zyloLiquidDocumentLink', ['documentId'])
    op.create_index('ix_zlDocumentLink_linkedEntityId', 'zyloLiquidDocumentLink', ['linkedEntityId'])


def downgrade() -> None:
    op.drop_table('zyloLiquidDocumentLink')
    op.drop_table('zyloLiquidDocument')
