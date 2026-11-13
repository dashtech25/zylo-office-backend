"""BE-094 : table `dispute` (litige fournisseur sur un paiement, ouverture et clôture).

Revision ID: e094a1c2d3e4
Revises: fd57ba293e8b
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e094a1c2d3e4"
down_revision: Union[str, None] = "fd57ba293e8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispute",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paymentAttemptId", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("providerRef", sa.String(160), nullable=False),
        sa.Column("openedAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["paymentAttemptId"], ["paymentAttempt.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("providerRef", name="uq_dispute_provider_ref"),
        comment="Litige fournisseur sur un paiement (BE-094) : ouverture et clôture par évènement fournisseur.",
    )
    op.create_index(op.f("ix_dispute_paymentAttemptId"), "dispute", ["paymentAttemptId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dispute_paymentAttemptId"), table_name="dispute")
    op.drop_table("dispute")
