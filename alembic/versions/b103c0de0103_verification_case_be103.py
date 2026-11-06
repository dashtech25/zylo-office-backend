"""Table verification_case : demande et statut de vérification d'organisation (BE-103)

Revision ID: b103c0de0103
Revises: be102c0de0102
Create Date: 2026-11-06

Crée `verification_case` : un cas par dépôt, rattaché à l'organisation. `statut` est contraint
aux quatre valeurs de la fiche (`verification_pending`, `verification_required`, `verified`,
`rejected`). `motifInterne` (texte, nullable) reste en base et n'est jamais renvoyé par l'API.

Downgrade : suppression de l'index puis de la table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b103c0de0103'
down_revision: Union[str, None] = 'be102c0de0102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'verification_case',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('organizationId', postgresql.UUID(as_uuid=True), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('statut', sa.String(length=32), nullable=False),
        sa.Column('motifInterne', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "statut IN ('verification_pending', 'verification_required', 'verified', 'rejected')",
            name='ck_verification_case_statut',
        ),
        comment="Cas de vérification d'organisation ; motif interne jamais exposé (BE-103).",
    )
    op.create_index(op.f('ix_verification_case_organizationId'), 'verification_case', ['organizationId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_verification_case_organizationId'), table_name='verification_case')
    op.drop_table('verification_case')
