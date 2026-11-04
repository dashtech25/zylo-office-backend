"""BE-072 : registre d'idempotence et colonnes de version optimiste.

Crée `idempotency_record` (portée principal + route + clé, empreinte de commande,
résultat rejouable) et ajoute `version` (entier, défaut 1) à `subscription` et `invoice`.

Revision ID: e072b1c2d3a4
Revises: b7c8d9e0f123
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e072b1c2d3a4"
down_revision: Union[str, None] = "b7c8d9e0f123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_record",
        sa.Column("scopeKey", sa.Text(), nullable=False),
        sa.Column("idempotencyKey", sa.Text(), nullable=False),
        sa.Column("commandHash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resultRef", sa.String(64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scopeKey", name="uq_idempotency_record_scope"),
        comment="Registre d'idempotence : portée principal + route + clé, empreinte de commande, résultat rejouable.",
    )
    op.add_column("subscription", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("invoice", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("invoice", "version")
    op.drop_column("subscription", "version")
    op.drop_table("idempotency_record")
