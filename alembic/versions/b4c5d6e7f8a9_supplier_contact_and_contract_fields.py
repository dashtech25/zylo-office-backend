"""supplier_contact_and_contract_fields

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidSupplier', sa.Column('category', sa.String(20), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('contactName', sa.String(150), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('contactRole', sa.String(100), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('contactPhone', sa.String(30), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('contactEmail', sa.String(255), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('website', sa.String(255), nullable=True))
    op.add_column('zyloLiquidSupplier', sa.Column('address', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_zlSupplier_category',
        'zyloLiquidSupplier',
        "category IS NULL OR category IN ('carburant','equipement','maintenance','securite','service','autre')",
    )

    op.add_column('zyloLiquidStationSupplier', sa.Column('contractReference', sa.String(100), nullable=True))
    op.add_column('zyloLiquidStationSupplier', sa.Column('contractType', sa.String(60), nullable=True))
    op.add_column('zyloLiquidStationSupplier', sa.Column('contractStartDate', sa.Date(), nullable=True))
    op.add_column('zyloLiquidStationSupplier', sa.Column('contractEndDate', sa.Date(), nullable=True))
    op.add_column('zyloLiquidStationSupplier', sa.Column('equipmentTags', sa.Text(), nullable=True))
    op.create_index(op.f('ix_zyloLiquidStationSupplier_contractEndDate'), 'zyloLiquidStationSupplier', ['contractEndDate'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zyloLiquidStationSupplier_contractEndDate'), table_name='zyloLiquidStationSupplier')
    op.drop_column('zyloLiquidStationSupplier', 'equipmentTags')
    op.drop_column('zyloLiquidStationSupplier', 'contractEndDate')
    op.drop_column('zyloLiquidStationSupplier', 'contractStartDate')
    op.drop_column('zyloLiquidStationSupplier', 'contractType')
    op.drop_column('zyloLiquidStationSupplier', 'contractReference')

    op.drop_constraint('ck_zlSupplier_category', 'zyloLiquidSupplier', type_='check')
    op.drop_column('zyloLiquidSupplier', 'address')
    op.drop_column('zyloLiquidSupplier', 'website')
    op.drop_column('zyloLiquidSupplier', 'contactEmail')
    op.drop_column('zyloLiquidSupplier', 'contactPhone')
    op.drop_column('zyloLiquidSupplier', 'contactRole')
    op.drop_column('zyloLiquidSupplier', 'contactName')
    op.drop_column('zyloLiquidSupplier', 'category')
