"""États d'exécution des commandes opérateur (BE-126).

Revision ID: b126a0de0126
Revises: f32497e0328e
Create Date: 2026-11-05

Élargit la contrainte `ck_admin_command_status` aux états produits par le pipeline
d'exécution (`app.operator.guard`) : `executee` (effet confirmé par le domaine),
`echec` (exception du domaine) et `resultat_inconnu` (CA-5, arrêt sans second appel).
Aucune table n'est ajoutée : le pipeline écrit dans `admin_command` et `audit_event`.

Downgrade : les commandes exécutées, en échec ou au résultat inconnu repassent à
`approuvee` si elles ont une décision d'approbation, sinon à `intention`, et leur
résultat est effacé. Cette réversion perd la trace d'exécution ; elle n'est à utiliser
qu'en local ou sur une base de test.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b126a0de0126"
down_revision: Union[str, None] = "f32497e0328e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_admin_command_status", "admin_command", type_="check")
    op.create_check_constraint(
        "ck_admin_command_status",
        "admin_command",
        "status IN ('intention', 'approuvee', 'rejetee', 'executee', 'echec', 'resultat_inconnu')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE admin_command SET status = 'approuvee', result = NULL "
        "WHERE status IN ('executee', 'echec', 'resultat_inconnu') AND \"approverId\" IS NOT NULL"
    )
    op.execute(
        "UPDATE admin_command SET status = 'intention', result = NULL "
        "WHERE status IN ('executee', 'echec', 'resultat_inconnu')"
    )
    op.drop_constraint("ck_admin_command_status", "admin_command", type_="check")
    op.create_check_constraint(
        "ck_admin_command_status",
        "admin_command",
        "status IN ('intention', 'approuvee', 'rejetee')",
    )
