"""BE-166 : outbox d'événements et consommation idempotente.

Crée `outbox_evenement` (événements validés, rattachés au tenant, unique par `eventId`)
et `consommation_evenement` (unique par couple consommateur / événement).

Revision ID: c166e0f1a2b3
Revises: 12a5bb79f642
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c166e0f1a2b3"
down_revision: Union[str, None] = "12a5bb79f642"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_evenement",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("eventId", sa.UUID(), nullable=False),
        sa.Column("eventType", sa.String(150), nullable=False),
        sa.Column("schemaVersion", sa.Integer(), nullable=False),
        sa.Column("tenantId", sa.UUID(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("statut", sa.String(20), server_default="publie", nullable=False),
        sa.Column("publieAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("statut IN ('publie')", name="ck_outbox_evenement_statut"),
        sa.ForeignKeyConstraint(["tenantId"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eventId", name="uq_outbox_evenement_eventId"),
        comment="Outbox : événements de domaine écrits dans la transaction métier, publiés après commit.",
    )
    op.create_index("ix_outbox_evenement_eventType", "outbox_evenement", ["eventType"])
    op.create_index("ix_outbox_evenement_tenantId", "outbox_evenement", ["tenantId"])

    op.create_table(
        "consommation_evenement",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("consommateur", sa.String(150), nullable=False),
        sa.Column("eventId", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["eventId"], ["outbox_evenement.eventId"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consommateur", "eventId", name="uq_consommation_evenement_consommateur_event"),
        comment="Consommation idempotente : un consommateur ne traite un événement qu'une fois.",
    )
    op.create_index("ix_consommation_evenement_eventId", "consommation_evenement", ["eventId"])


def downgrade() -> None:
    op.drop_index("ix_consommation_evenement_eventId", table_name="consommation_evenement")
    op.drop_table("consommation_evenement")
    op.drop_index("ix_outbox_evenement_tenantId", table_name="outbox_evenement")
    op.drop_index("ix_outbox_evenement_eventType", table_name="outbox_evenement")
    op.drop_table("outbox_evenement")
