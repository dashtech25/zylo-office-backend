"""Add hashed one-time password reset tokens.

Revision ID: e3c4a8f1b2d6
Revises: d8e9f0a1b2c3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e3c4a8f1b2d6"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "passwordResetToken",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("userId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tokenHash", sa.String(length=64), nullable=False),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["userId"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tokenHash", name="uq_passwordResetToken_tokenHash"),
        comment="Jeton de récupération de compte, haché, à usage unique et expiration courte.",
    )
    op.create_index("ix_passwordResetToken_userId", "passwordResetToken", ["userId"])
    op.create_index(
        "uq_passwordResetToken_open_per_user",
        "passwordResetToken",
        ["userId"],
        unique=True,
        postgresql_where=sa.text('"usedAt" IS NULL AND "revokedAt" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_passwordResetToken_open_per_user", table_name="passwordResetToken")
    op.drop_index("ix_passwordResetToken_userId", table_name="passwordResetToken")
    op.drop_table("passwordResetToken")
