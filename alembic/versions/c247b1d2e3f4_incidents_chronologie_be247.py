"""BE-247 : incidents d'exploitation et chronologie append-only

Revision ID: c247b1d2e3f4
Revises: 290f30a9bcbf
Create Date: 2026-11-05

Crée `incidents` (owner, état et horodatage obligatoires, tenant facultatif) et
`incident_events` (chronologie ordonnée par `sequence`). Pose sur `incident_events`
un trigger BEFORE UPDATE OR DELETE qui lève `restrict_violation` pour toute ligne :
la chronologie est en ajout seul (CA-2), comme `audit_event` (BE-260).

Downgrade : retire le trigger, sa fonction puis les deux tables. Les données
d'incident sont perdues au downgrade ; il ne doit pas être joué en production
sans sauvegarde.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c247b1d2e3f4"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("occurredAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenantId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=True),
        sa.CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_incidents_severity"),
        sa.CheckConstraint("state IN ('ouvert','en_cours','resolu','cloture')", name="ck_incidents_state"),
        comment="Incidents d'exploitation : owner, état et horodatage obligatoires (BE-247).",
    )
    op.create_index("ix_incidents_tenantId", "incidents", ["tenantId"])

    op.create_table(
        "incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incidentId", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("eventType", sa.String(length=60), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("actorUserId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("auditEventId", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurredAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Chronologie append-only des incidents ; UPDATE et DELETE refusés par trigger (BE-247).",
    )
    op.create_index("ix_incident_events_incidentId", "incident_events", ["incidentId"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION incident_events_ajout_seul()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'incident_events : chronologie immuable (BE-247)'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER incident_events_ajout_seul
        BEFORE UPDATE OR DELETE ON incident_events
        FOR EACH ROW
        EXECUTE FUNCTION incident_events_ajout_seul();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS incident_events_ajout_seul ON incident_events")
    op.execute("DROP FUNCTION IF EXISTS incident_events_ajout_seul()")
    op.drop_index("ix_incident_events_incidentId", table_name="incident_events")
    op.drop_table("incident_events")
    op.drop_index("ix_incidents_tenantId", table_name="incidents")
    op.drop_table("incidents")
