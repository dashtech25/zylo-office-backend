"""merge heads for be-196

Revision ID: 0001be196001
Revises: c117e5a1b2d3, be210c0d1e2f
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0001be196001'
down_revision: Union[str, Sequence[str], None] = ('c117e5a1b2d3', 'be210c0d1e2f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration - fuses divergent branches
    # Also adds BE-196 columns to organizationModule
    op.add_column('organizationModule', sa.Column('state', sa.String(50), nullable=True, comment="État du cycle de vie (active, failed)."))
    op.add_column('organizationModule', sa.Column('version', sa.Integer(), nullable=True, comment="Version de l'état pour détecter les conflits."))
    op.add_column('organizationModule', sa.Column('operationId', postgresql.UUID(as_uuid=True), nullable=True, comment="Identifiant de la dernière opération d'activation (BE-196)."))


def downgrade() -> None:
    # Merge migration - reverse the column additions
    op.drop_column('organizationModule', 'operationId')
    op.drop_column('organizationModule', 'version')
    op.drop_column('organizationModule', 'state')
