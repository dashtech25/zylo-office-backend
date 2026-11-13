"""BE-045 : entitlements organisation (version d'état, index organisation/module, défauts retirés).

Revision ID: a045b1c2d3e4
Revises: d4e5f6a7b8c9

Ce que fait la migration sur `subscription_entitlement` (table créée par BE-024) :
- ajoute `stateVersion` (entier non nul, 1 par défaut pour les lignes existantes) : compteur
  de version de l'état, incrémenté par les écritures d'état futures ;
- ajoute l'index `ix_subscription_entitlement_organizationId_moduleCode` sur
  (organizationId, moduleCode) : lecture des entitlements d'une organisation par module ;
- retire les valeurs par défaut serveur de `niveauApplication` (scope) et de
  `sourceAttribution` (source) : un entitlement doit dire explicitement son niveau et sa
  source. Les lignes existantes gardent leur valeur ; seule l'insertion future change.

Les lignes existantes ne sont pas réécrites. Le modèle SQLAlchemy retire lui aussi les
défauts Python correspondants (app/billing/models.py) : les deux doivent rester alignés.

Retour arrière : supprime l'index et `stateVersion`, et rétablit les défauts serveur
`organisation` et `offre`, comme dans la migration BE-024. Aucune donnée n'est perdue.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a045b1c2d3e4"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_entitlement",
        sa.Column("stateVersion", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_subscription_entitlement_organizationId_moduleCode",
        "subscription_entitlement",
        ["organizationId", "moduleCode"],
    )
    op.alter_column("subscription_entitlement", "niveauApplication", server_default=None)
    op.alter_column("subscription_entitlement", "sourceAttribution", server_default=None)


def downgrade() -> None:
    op.alter_column("subscription_entitlement", "sourceAttribution", server_default="offre")
    op.alter_column("subscription_entitlement", "niveauApplication", server_default="organisation")
    op.drop_index("ix_subscription_entitlement_organizationId_moduleCode", table_name="subscription_entitlement")
    op.drop_column("subscription_entitlement", "stateVersion")
