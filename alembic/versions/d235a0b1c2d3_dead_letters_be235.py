"""Table des lettres mortes de consommation d'événements (BE-235).

Revision ID: d235a0b1c2d3
Revises: 290f30a9bcbf
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d235a0b1c2d3"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letters",
        sa.Column("eventId", sa.UUID(), nullable=False),
        sa.Column("consommateur", sa.String(length=150), nullable=False),
        sa.Column("motif", sa.String(length=200), nullable=False),
        sa.Column("tentatives", sa.Integer(), nullable=False),
        sa.Column("tenantId", sa.UUID(), nullable=False),
        sa.Column("statut", sa.String(length=20), server_default="en_attente", nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("rejoueAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("statut IN ('en_attente', 'rejoue')", name="ck_dead_letters_statut"),
        sa.ForeignKeyConstraint(["eventId"], ["outbox_evenement.eventId"]),
        sa.ForeignKeyConstraint(["tenantId"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consommateur", "eventId", name="uq_dead_letters_consommateur_event"),
        comment="File de lettres mortes : événements en échec définitif pour un consommateur, rejouables par un opérateur.",
    )
    op.create_index(op.f("ix_dead_letters_eventId"), "dead_letters", ["eventId"], unique=False)
    op.create_index(op.f("ix_dead_letters_tenantId"), "dead_letters", ["tenantId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dead_letters_tenantId"), table_name="dead_letters")
    op.drop_index(op.f("ix_dead_letters_eventId"), table_name="dead_letters")
    op.drop_table("dead_letters")
