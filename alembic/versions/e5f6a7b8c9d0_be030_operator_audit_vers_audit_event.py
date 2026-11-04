"""BE-030 : les lectures opérateur sont journalisées dans audit_event.

Revision ID: e5f6a7b8c9d0
Revises: 82b12c50c3f6
Create Date: 2026-11-03

Décision D2 : une seule table d'audit (`audit_event`, BE-007). Cette migration
reprend les lignes de `operatorAuditLog` dans `audit_event`, puis supprime la
table :
- `action` devient `operator.<action>` ;
- `scopeResourceType` = `scope`, `scopeResourceId` = cible si portée organisation ;
- `entityType` / `entityId` = `targetType` / `targetId` ;
- `result` = `refused` si l'issue vaut `refused`, sinon `success` ;
- `changes` = `{"outcome": <issue d'origine>}` ;
- `request_id` = `requestId` ; `eventId` = identifiant de la ligne ;
- `organizationId` nul (portée plateforme ou organisation non reprise).

Downgrade : recrée `operatorAuditLog` et y recopie les lignes `operator.%`,
puis retire ces lignes de `audit_event`. Les lignes d'audit métier ne sont pas
touchées. Migration marquée destructive dans app/core/migrations.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "82b12c50c3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO audit_event (
            id, "organizationId", "actorUserId", action, "entityType", "entityId",
            "scopeResourceType", "scopeResourceId", summary, changes,
            request_id, result, "eventId", "actorType", "schemaVersion", "createdAt"
        )
        SELECT
            id,
            NULL,
            "actorUserId",
            'operator.' || action,
            "targetType",
            "targetId",
            scope,
            CASE WHEN scope = 'organization' THEN "targetId" ELSE NULL END,
            'Lecture opérateur reprise : ' || action || ' (' || "targetType" || ').',
            jsonb_build_object('outcome', outcome)::json,
            "requestId",
            CASE WHEN outcome = 'refused' THEN 'refused' ELSE 'success' END,
            id::text,
            'humain',
            1,
            "createdAt"
        FROM "operatorAuditLog"
        """
    )
    op.drop_index(op.f("ix_operatorAuditLog_createdAt"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_requestId"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_action"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_scope"), table_name="operatorAuditLog")
    op.drop_index(op.f("ix_operatorAuditLog_actorUserId"), table_name="operatorAuditLog")
    op.drop_table("operatorAuditLog")


def downgrade() -> None:
    op.create_table(
        "operatorAuditLog",
        sa.Column("actorUserId", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("targetType", sa.String(length=80), nullable=False),
        sa.Column("targetId", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("requestId", sa.String(length=128), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["actorUserId"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operatorAuditLog_actorUserId"), "operatorAuditLog", ["actorUserId"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_scope"), "operatorAuditLog", ["scope"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_action"), "operatorAuditLog", ["action"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_requestId"), "operatorAuditLog", ["requestId"], unique=False)
    op.create_index(op.f("ix_operatorAuditLog_createdAt"), "operatorAuditLog", ["createdAt"], unique=False)
    op.execute(
        """
        INSERT INTO "operatorAuditLog" (
            id, "actorUserId", scope, action, "targetType", "targetId", outcome, "requestId", "createdAt"
        )
        SELECT
            id,
            "actorUserId",
            COALESCE("scopeResourceType", 'platform'),
            substring(action from 10),
            "entityType",
            "entityId",
            COALESCE(changes->>'outcome', result),
            request_id,
            "createdAt"
        FROM audit_event
        WHERE action LIKE 'operator.%'
        """
    )
    op.execute("DELETE FROM audit_event WHERE action LIKE 'operator.%'")
