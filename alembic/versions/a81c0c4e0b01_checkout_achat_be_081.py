"""Table checkout : achat par checkout (BE-081).

Crée `checkout` (id, quoteId, status, version, createdAt). `quoteId` référence le devis
accepté (`quote.id`). `status` est contraint aux six états de la machine d'état
(open, pending, completed, failed, cancelled, expired) ; BE-081 n'écrit que `open`.
Downgrade : suppression de la table, sans effet sur `quote` ni `consent_record`.

Revision ID: a81c0c4e0b01
Revises: 254220e168b5
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a81c0c4e0b01'
down_revision: Union[str, None] = '254220e168b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'checkout',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('quoteId', postgresql.UUID(as_uuid=True), sa.ForeignKey('quote.id'), nullable=False,
                  comment='Devis accepté dont le checkout est issu.'),
        sa.Column('status', sa.String(length=20), nullable=False,
                  comment='open, pending, completed, failed, cancelled ou expired.'),
        sa.Column('version', sa.Integer(), nullable=False,
                  comment='Verrou optimiste (BE-072), incrémenté à chaque transition.'),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'completed', 'failed', 'cancelled', 'expired')",
            name='ck_checkout_status',
        ),
        comment="Checkout d'achat issu d'un devis accepté (BE-081). Colonnes exactes non définies (QE-FAC-04).",
    )
    op.create_index(op.f('ix_checkout_quoteId'), 'checkout', ['quoteId'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_checkout_quoteId'), table_name='checkout')
    op.drop_table('checkout')
