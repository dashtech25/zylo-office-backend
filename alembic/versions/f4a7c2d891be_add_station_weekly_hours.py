"""add station weeklyHours (per-day opening hours, P2 audit stations)

Revision ID: f4a7c2d891be
Revises: c3e8f1a9b5d2
Create Date: 2026-09-16 15:45:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f4a7c2d891be'
down_revision: Union[str, None] = 'c3e8f1a9b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidStation', sa.Column('weeklyHours', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('zyloLiquidStation', 'weeklyHours')
