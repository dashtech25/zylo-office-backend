"""Migration run table for BE-198.

Revision ID: be198a0b1c2d
Revises:
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be198a0b1c2d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('migration_run',
    sa.Column('migrationId', sa.UUID(), nullable=False),
    sa.Column('state', sa.String(length=50), nullable=False, server_default='pending'),
    sa.Column('checkpoint', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('lockOwner', sa.String(length=255), nullable=True),
    sa.Column('leaseExpiresAt', sa.DateTime(), nullable=True),
    sa.Column('startedAt', sa.DateTime(), nullable=True),
    sa.Column('report', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('migrationId'),
    comment='Migration run state tracking for BE-198: dry-run, run, resume, rollback'
    )
    op.create_index(op.f('ix_migration_run_state'), 'migration_run', ['state'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_migration_run_state'), table_name='migration_run')
    op.drop_table('migration_run')
