"""role.moduleCode : rattachement d'un rôle à un module (T-018)

Revision ID: a7d3c1e9f024
Revises: e2f3a4b5c6d7
Create Date: 2026-10-09

Intention : ajouter la colonne `role.moduleCode` (nullable, FK vers
`module.code`, index) et rien d'autre. Migration purement additive :
- aucune ligne existante n'est modifiée (la colonne reste NULL = rôle
  transverse, comportement actuel inchangé) ;
- aucun rattachement n'est fait ici : le rattachement des rôles par défaut
  est un backfill explicite et rejouable (rbac/module_backfill.py, script
  scripts/backfill_module_roles.py), jamais exécuté au démarrage ;
- le downgrade supprime la colonne : les rattachements qu'elle contenait ne
  sont PAS restaurés (les rôles redeviennent transverses). Voir
  docs/architecture/securite/roles-par-module.md, section « Retour arrière ».
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7d3c1e9f024'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('role', sa.Column('moduleCode', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_role_moduleCode'), 'role', ['moduleCode'], unique=False)
    op.create_foreign_key('fk_role_moduleCode_module', 'role', 'module', ['moduleCode'], ['code'])


def downgrade() -> None:
    op.drop_constraint('fk_role_moduleCode_module', 'role', type_='foreignkey')
    op.drop_index(op.f('ix_role_moduleCode'), table_name='role')
    op.drop_column('role', 'moduleCode')
