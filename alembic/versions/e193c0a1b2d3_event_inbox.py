"""BE-193 : table `event_inbox` de réception idempotente des événements.

Crée `event_inbox` : une ligne par couple (`subscriber`, `eventId`), statut parmi processed,
retry et quarantine, compteur de tentatives, et colonnes d'agrégat pour l'ordre (CA-3). La
contrainte d'unicité (`subscriber`, `eventId`) rend la réception idempotente (CA-1).

Pas de clé étrangère sur `tenantId` ni `eventId` : un événement d'un tenant inconnu doit
pouvoir être mis en quarantaine (CA-2), et l'inbox accepte des événements hors outbox locale.

Downgrade : suppression de la table. Les états de réception et de quarantaine sont perdus.

Revision ID: e193c0a1b2d3
Revises: 343483f94352
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e193c0a1b2d3"
down_revision: Union[str, None] = "343483f94352"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_inbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscriber", sa.String(150), nullable=False),
        sa.Column("eventId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenantId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eventType", sa.String(150), nullable=False),
        sa.Column("schemaVersion", sa.Integer(), nullable=False),
        sa.Column("aggregateType", sa.String(100), nullable=True),
        sa.Column("aggregateId", sa.String(200), nullable=True),
        sa.Column("aggregateVersion", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("receivedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subscriber", "eventId", name="uq_event_inbox_subscriber_event"),
        sa.CheckConstraint("status IN ('processed', 'retry', 'quarantine')", name="ck_event_inbox_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_event_inbox_attempts"),
        comment="Inbox consommateur : réception idempotente, hors ordre et quarantaine des événements (BE-193).",
    )
    op.create_index("ix_event_inbox_eventId", "event_inbox", ["eventId"])
    op.create_index("ix_event_inbox_tenantId", "event_inbox", ["tenantId"])


def downgrade() -> None:
    op.drop_index("ix_event_inbox_tenantId", table_name="event_inbox")
    op.drop_index("ix_event_inbox_eventId", table_name="event_inbox")
    op.drop_table("event_inbox")
