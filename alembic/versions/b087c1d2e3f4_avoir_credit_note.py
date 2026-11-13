"""BE-087 : table `credit_note` (avoir sur une facture finalisée).

Revision ID: b087c1d2e3f4
Revises: 254220e168b5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b087c1d2e3f4"
down_revision: Union[str, None] = "254220e168b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_note",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoiceId", sa.UUID(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["invoiceId"], ["invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Avoir émis sur une facture finalisée (BE-087). Append-only ; la facture d'origine n'est pas modifiée.",
    )
    op.create_index(op.f("ix_credit_note_invoiceId"), "credit_note", ["invoiceId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_note_invoiceId"), table_name="credit_note")
    op.drop_table("credit_note")
