"""BE-215 : registre des versions de contrat (contract_version)

Revision ID: be215a1b2c3d
Revises: 90f0db41ebb6
Create Date: 2026-11-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'be215a1b2c3d'
down_revision: Union[str, None] = '90f0db41ebb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contract_version',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('contractName', sa.String(length=150), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='current', nullable=False),
        sa.Column('removedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('schemaJson', sa.JSON(), nullable=False),
        sa.CheckConstraint('version >= 1', name='ck_contract_version_version'),
        sa.CheckConstraint("status IN ('current', 'deprecated')", name='ck_contract_version_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contractName', 'version', name='uq_contract_version_contract_version'),
        comment="Registre des versions de contrat : compatibilité, coexistence N/N-1 et dépréciation (BE-215).",
    )
    op.create_index(op.f('ix_contract_version_contractName'), 'contract_version', ['contractName'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_contract_version_contractName'), table_name='contract_version')
    op.drop_table('contract_version')
