"""usage_snapshot : projection de l'usage par organisation (BE-108, lecture seule)

Revision ID: b108c4a1d2e3
Revises: 54ba4aaf7237
Create Date: 2026-11-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b108c4a1d2e3'
down_revision: Union[str, None] = '54ba4aaf7237'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage_snapshot',
        sa.Column('organizationId', sa.UUID(), nullable=False),
        sa.Column('measuredAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('granularity', sa.String(length=30), nullable=False),
        sa.Column('aggregates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('limits', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organizationId'], ['organization.id']),
        sa.PrimaryKeyConstraint('id'),
        comment="Projection de l'usage par organisation, publiée par PH-09 (BE-108, lecture seule).",
    )
    op.create_index(op.f('ix_usage_snapshot_organizationId'), 'usage_snapshot', ['organizationId'], unique=False)
    op.create_index(op.f('ix_usage_snapshot_measuredAt'), 'usage_snapshot', ['measuredAt'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usage_snapshot_measuredAt'), table_name='usage_snapshot')
    op.drop_index(op.f('ix_usage_snapshot_organizationId'), table_name='usage_snapshot')
    op.drop_table('usage_snapshot')
