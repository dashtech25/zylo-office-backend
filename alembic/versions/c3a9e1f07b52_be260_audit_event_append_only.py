"""BE-260 : `audit_event` en ajout seul pour toutes les entrées (CA-5)

Revision ID: c3a9e1f07b52
Revises: 169de7fb56af
Create Date: 2026-11-04

Pose sur `audit_event` (table de BE-007, aucune table ajoutée) un trigger
BEFORE UPDATE OR DELETE, valable pour toute ligne. Le trigger BE-073
(`audit_event_facturation_immuable`) ne couvre que les actions `billing.*` ;
celui-ci couvre le journal entier, conformément à la définition BE-260
(« toute tentative d'UPDATE ou de DELETE échoue »).

Le trigger lève une exception SQL (`restrict_violation`), donc aucune session
applicative ne peut contourner le journal sans supprimer le trigger.
TRUNCATE n'est pas concerné (pas de trigger ligne) : la purge des tests reste
possible.

Downgrade : retire le trigger puis la fonction ; aucune donnée n'est modifiée.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3a9e1f07b52"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_event_ajout_seul()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event : entrée d''audit immuable (BE-260)'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_ajout_seul
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW
        EXECUTE FUNCTION audit_event_ajout_seul();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_ajout_seul ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_ajout_seul()")
