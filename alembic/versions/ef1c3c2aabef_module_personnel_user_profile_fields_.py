"""module personnel: user profile fields + station staff profile

Module Personnel (Centre administratif et opérationnel de la station,
mockup emalioration/personnel/) — colonnes additives sur `user`
(firstName/lastName/phone/photoStorageReference/mustChangePassword) et
nouvelle table `zyloLiquidStationStaffProfile` (numéro d'employé, contrat,
station affectée, responsable direct). Tout additif, non destructif.

Revision ID: ef1c3c2aabef
Revises: 91faf138b6e2
Create Date: 2026-09-08 13:06:33.559878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ef1c3c2aabef'
down_revision: Union[str, None] = '91faf138b6e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user', sa.Column('firstName', sa.String(length=120), nullable=True))
    op.add_column('user', sa.Column('lastName', sa.String(length=120), nullable=True))
    op.add_column('user', sa.Column('phone', sa.String(length=20), nullable=True))
    op.add_column('user', sa.Column('photoStorageReference', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('mustChangePassword', sa.Boolean(), server_default='false', nullable=False))

    op.create_table(
        'zyloLiquidStationStaffProfile',
        sa.Column('organizationId', sa.UUID(), nullable=False),
        sa.Column('userId', sa.UUID(), nullable=False),
        sa.Column('employeeNumber', sa.String(length=50), nullable=True),
        sa.Column('contractType', sa.String(length=50), nullable=True),
        sa.Column('assignedStationId', sa.UUID(), nullable=True),
        sa.Column('directManagerUserId', sa.UUID(), nullable=True),
        sa.Column('assignedAt', sa.Date(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assignedStationId'], ['zyloLiquidStation.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['directManagerUserId'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organizationId'], ['organization.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['userId'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organizationId', 'userId', name='uq_zlStationStaffProfile_org_user'),
        comment="Informations de poste d'un membre du personnel — numéro d'employé, contrat, station affectée, responsable direct.",
    )
    op.create_index(op.f('ix_zyloLiquidStationStaffProfile_assignedStationId'), 'zyloLiquidStationStaffProfile', ['assignedStationId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidStationStaffProfile_organizationId'), 'zyloLiquidStationStaffProfile', ['organizationId'], unique=False)
    op.create_index(op.f('ix_zyloLiquidStationStaffProfile_userId'), 'zyloLiquidStationStaffProfile', ['userId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zyloLiquidStationStaffProfile_userId'), table_name='zyloLiquidStationStaffProfile')
    op.drop_index(op.f('ix_zyloLiquidStationStaffProfile_organizationId'), table_name='zyloLiquidStationStaffProfile')
    op.drop_index(op.f('ix_zyloLiquidStationStaffProfile_assignedStationId'), table_name='zyloLiquidStationStaffProfile')
    op.drop_table('zyloLiquidStationStaffProfile')

    op.drop_column('user', 'mustChangePassword')
    op.drop_column('user', 'photoStorageReference')
    op.drop_column('user', 'phone')
    op.drop_column('user', 'lastName')
    op.drop_column('user', 'firstName')
