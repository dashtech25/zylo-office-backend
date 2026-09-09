"""regulatory_document_notes_responsible

Revision ID: a3b4c5d6e7f8
Revises: ef1c3c2aabef
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'ef1c3c2aabef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidRegulatoryDocument', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('zyloLiquidRegulatoryDocument', sa.Column('responsibleUserId', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_zlRegulatoryDocument_responsibleUserId_user',
        'zyloLiquidRegulatoryDocument', 'user',
        ['responsibleUserId'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_zlRegulatoryDocument_responsibleUserId_user', 'zyloLiquidRegulatoryDocument', type_='foreignkey')
    op.drop_column('zyloLiquidRegulatoryDocument', 'responsibleUserId')
    op.drop_column('zyloLiquidRegulatoryDocument', 'notes')
