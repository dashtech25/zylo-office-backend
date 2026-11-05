"""BE-093 : table `refund` (remboursement d'un paiement réussi, approbation humaine).

Revision ID: e093a7b1c2d4
Revises: 3a2990daf8ef
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e093a7b1c2d4"
down_revision: Union[str, None] = "3a2990daf8ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refund",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paymentAttemptId", sa.UUID(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approverId", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["paymentAttemptId"], ["paymentAttempt.id"]),
        sa.ForeignKeyConstraint(["approverId"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paymentAttemptId", "request_id", name="uq_refund_payment_request"),
        comment="Remboursement d'un paiement réussi (BE-093) : approbation humaine avant tout envoi fournisseur.",
    )
    op.create_index(op.f("ix_refund_paymentAttemptId"), "refund", ["paymentAttemptId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refund_paymentAttemptId"), table_name="refund")
    op.drop_table("refund")
