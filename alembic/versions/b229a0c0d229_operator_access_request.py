"""Accès opérateur nominatif, JIT et approbation (BE-229).

Revision ID: b229a0c0d229
Revises: 290f30a9bcbf
Create Date: 2026-11-05

Crée `operator_access_request` : demandes et accès opérateur à un tenant, pour une
action, bornés dans le temps et approuvés par un autre opérateur (voir
app/operator/access.py). Downgrade : suppression de la table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b229a0c0d229'
down_revision: Union[str, None] = '290f30a9bcbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'operator_access_request',
        sa.Column('accessRequestId', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('operatorId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('tenantId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('motif', sa.String(length=500), nullable=False),
        sa.Column('dureeMinutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('requestedAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expiresAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approverId', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('approvedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revokedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revokedById', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=True),
        sa.CheckConstraint("status IN ('demandee', 'approuvee', 'revoquee')", name='ck_operator_access_request_status'),
        sa.CheckConstraint('"dureeMinutes" >= 1 AND "dureeMinutes" <= 240', name='ck_operator_access_request_duree'),
        comment="Demandes et accès opérateur nominatifs, JIT et approuvés (BE-229).",
    )
    op.create_index('ix_operator_access_request_operatorId', 'operator_access_request', ['operatorId'])
    op.create_index('ix_operator_access_request_tenantId', 'operator_access_request', ['tenantId'])


def downgrade() -> None:
    op.drop_index('ix_operator_access_request_tenantId', table_name='operator_access_request')
    op.drop_index('ix_operator_access_request_operatorId', table_name='operator_access_request')
    op.drop_table('operator_access_request')
