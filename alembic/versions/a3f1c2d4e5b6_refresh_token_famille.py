"""refreshToken : famille de rotation (T-020)

Migration additive. Chaque jeton existant devient la racine de sa propre famille
(familyId = id), donc aucune session ouverte n'est coupée au déploiement.

Revision ID: a3f1c2d4e5b6
Revises: 7c2e9a1f4b8d
Create Date: 2026-10-09 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f1c2d4e5b6'
down_revision: Union[str, None] = '7c2e9a1f4b8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'refreshToken',
        sa.Column('familyId', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='Famille de rotation : révoquée entière en cas de réutilisation.'),
    )
    op.execute('UPDATE "refreshToken" SET "familyId" = id WHERE "familyId" IS NULL')
    op.alter_column('refreshToken', 'familyId', nullable=False)
    op.create_index(op.f('ix_refreshToken_familyId'), 'refreshToken', ['familyId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_refreshToken_familyId'), table_name='refreshToken')
    op.drop_column('refreshToken', 'familyId')
