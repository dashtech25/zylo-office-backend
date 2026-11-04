"""BE-056 : colonnes d'événements de transition de module sur audit_event.

Ajoute à `audit_event` (journal unique, BE-007) les colonnes nécessaires aux événements
de transition des modules : `subjectType`, `subjectId`, `eventName`, `origin`,
`correlationId`, `payloadMinimal`, et l'index composite `(organizationId, createdAt)`
demandé à BE-007 par la définition de BE-056. Toutes les colonnes sont nullables : les
entrées d'audit métier existantes restent valides sans reprise de données.

Revision ID: a056b1c2d3e4
Revises: f668520e8d62
Create Date: 2026-11-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a056b1c2d3e4"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_event", sa.Column("subjectType", sa.String(length=100), nullable=True))
    op.add_column("audit_event", sa.Column("subjectId", sa.UUID(), nullable=True))
    op.add_column("audit_event", sa.Column("eventName", sa.String(length=100), nullable=True))
    op.add_column("audit_event", sa.Column("origin", sa.String(length=32), nullable=True))
    op.add_column("audit_event", sa.Column("correlationId", sa.String(length=128), nullable=True))
    op.add_column("audit_event", sa.Column("payloadMinimal", sa.JSON(), nullable=True))
    op.create_index("ix_audit_event_subjectId", "audit_event", ["subjectId"])
    op.create_index("ix_audit_event_eventName", "audit_event", ["eventName"])
    op.create_index("ix_audit_event_correlationId", "audit_event", ["correlationId"])
    op.create_index("ix_audit_event_organizationId_createdAt", "audit_event", ["organizationId", "createdAt"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_organizationId_createdAt", table_name="audit_event")
    op.drop_index("ix_audit_event_correlationId", table_name="audit_event")
    op.drop_index("ix_audit_event_eventName", table_name="audit_event")
    op.drop_index("ix_audit_event_subjectId", table_name="audit_event")
    op.drop_column("audit_event", "payloadMinimal")
    op.drop_column("audit_event", "correlationId")
    op.drop_column("audit_event", "origin")
    op.drop_column("audit_event", "eventName")
    op.drop_column("audit_event", "subjectId")
    op.drop_column("audit_event", "subjectType")
