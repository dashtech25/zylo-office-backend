"""BE-073 : entrées financières de audit_event en append-only

Revision ID: a1d073b2c4e5
Revises: f668520e8d62
Create Date: 2026-11-04

Pose sur `audit_event` (table de BE-007, aucune table ajoutée) un trigger
PostgreSQL BEFORE UPDATE OR DELETE qui lève une erreur pour toute ligne dont
l'action commence par `billing.`. La trace d'un geste financier ne peut donc
plus être réécrite ni effacée, même par une requête directe. Les autres entrées
du journal (identité, rbac, etc.) ne sont pas touchées.

Le contrôle est fait par la base et non par le seul service : un script ou une
session SQL ne peut pas le contourner sans supprimer le trigger.

Downgrade : retire le trigger puis la fonction. Aucune donnée n'est modifiée.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1d073b2c4e5"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_event_facturation_immuable()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event : entrée financière (billing.*) immuable (BE-073)'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_facturation_immuable
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW
        WHEN (OLD.action LIKE 'billing.%')
        EXECUTE FUNCTION audit_event_facturation_immuable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_facturation_immuable ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_facturation_immuable()")
