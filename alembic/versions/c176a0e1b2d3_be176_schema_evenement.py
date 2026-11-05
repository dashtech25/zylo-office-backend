"""be176 registre des schémas d'événements versionnés

Revision ID: c176a0e1b2d3
Revises: 7c0052761f05
Create Date: 2026-11-05 12:00:00

Crée `schema_evenement` : une ligne par version de schéma d'un type d'événement (BE-176).
Unicité `(eventType, schemaVersion)`. Downgrade : suppression de la table, sans effet sur les
événements déjà publiés dans `outbox_evenement` (ils gardent leur `schemaVersion`).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c176a0e1b2d3"
down_revision: Union[str, None] = "7c0052761f05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schema_evenement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("eventType", sa.String(length=150), nullable=False),
        sa.Column("schemaVersion", sa.Integer(), nullable=False),
        sa.Column("schemaJson", sa.JSON(), nullable=False),
        sa.Column("compatibleDepuis", sa.Integer(), nullable=False),
        sa.Column("actif", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("eventType", "schemaVersion", name="uq_schema_evenement_version"),
        sa.CheckConstraint('"schemaVersion" >= 1', name="ck_schema_evenement_version"),
        sa.CheckConstraint(
            '"compatibleDepuis" >= 1 AND "compatibleDepuis" <= "schemaVersion"',
            name="ck_schema_evenement_compatible",
        ),
        comment="Registre des versions de schéma des types d'événements (catalogue, BE-176).",
    )
    op.create_index("ix_schema_evenement_eventType", "schema_evenement", ["eventType"])


def downgrade() -> None:
    op.drop_index("ix_schema_evenement_eventType", table_name="schema_evenement")
    op.drop_table("schema_evenement")
