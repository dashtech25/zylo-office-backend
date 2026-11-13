"""BE-074 : table de réception des événements fournisseurs `inbox_event`.

Crée `inbox_event` : une ligne par (fournisseur, identifiant d'événement), unique sur ce couple
(CA-2). Le statut ne prend que `applique` ou `hors_ordre` (CA-3). L'outbox n'est pas touchée :
elle appartient à BE-234 (`outbox_evenement`).

Revision ID: a074b1c2d3e4
Revises: f32497e0328e
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a074b1c2d3e4"
down_revision: Union[str, None] = "f32497e0328e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbox_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("providerEventId", sa.String(160), nullable=False),
        sa.Column("receivedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("quarantineFlag", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("status IN ('applique', 'hors_ordre')", name="ck_inbox_event_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "providerEventId", name="uq_inbox_event_provider_event"),
        comment="Inbox : événements fournisseurs reçus, idempotents par (fournisseur, identifiant) (BE-074).",
    )


def downgrade() -> None:
    op.drop_table("inbox_event")
