"""table loginAttempt : limitation de débit de l'authentification (T-012)

Revision ID: a9b8c7d6e5f4
Revises: e2f3a4b5c6d7
Create Date: 2026-10-09

Migration additive : une nouvelle table, aucune donnée existante touchée.
Stocke des empreintes (SHA-256), jamais d'email ni de mot de passe en clair.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'loginAttempt',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('action', sa.String(length=16), nullable=False, comment='login, register ou refresh'),
        sa.Column('scope', sa.String(length=8), nullable=False, comment='couple (IP, compte) ou ip'),
        sa.Column('keyHash', sa.String(length=64), nullable=False, comment='Empreinte SHA-256 de la clé de limitation'),
        sa.Column('outcome', sa.String(length=8), nullable=False, comment='failure ou success'),
        sa.Column('occurredAt', sa.DateTime(timezone=True), nullable=False, comment='Horodatage applicatif de la tentative'),
        comment="Échecs d'authentification et couples (IP, compte) connus — limitation de débit T-012. Empreintes uniquement.",
    )
    op.create_index(op.f('ix_loginAttempt_keyHash'), 'loginAttempt', ['keyHash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_loginAttempt_keyHash'), table_name='loginAttempt')
    op.drop_table('loginAttempt')
