"""Scope tenant : attribution de rôle liée au tenant du rôle (BE-182, CA-2).

Revision ID: c1e8be182a01
Revises: 254220e168b5
Create Date: 2026-11-05

Objet : empêcher qu'une attribution (`userRole`) pointe vers un rôle d'une autre
organisation. Pour cela :
- `role` reçoit une unicité (`organizationId`, `id`), cible d'une clé étrangère
  composite (la clé primaire `id` seule ne suffit pas à la référencer avec le
  tenant) ;
- `userRole` reçoit la clé étrangère composite (`organizationId`, `roleId`) vers
  `role` (`organizationId`, `id`). Une ligne dont le tenant diffère de celui du
  rôle est refusée par la base.

La clé `uq_role_org_code` et la clé étrangère simple `userRole.roleId -> role.id`
restent en place : cette migration ajoute une garantie, elle n'en retire aucune.

Portée : seul le couple `userRole` -> `role` est durci ici (pilote de BE-182). Les
autres références tenant-scoped vers des tables tenant-scoped restent à traiter
(question ouverte dans POINTS-OUVERTS, tâche BE-182).

Données existantes : si une ligne `userRole` pointe déjà vers un rôle d'une autre
organisation, la création de la clé échoue et la migration s'arrête sans rien
modifier (transaction Alembic). Il faut alors corriger ces lignes à la main, pas
désactiver la contrainte.

Downgrade : supprime la clé composite puis l'unicité, dans l'ordre inverse.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c1e8be182a01"
down_revision: Union[str, None] = "254220e168b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_role_org_id", "role", ["organizationId", "id"])
    op.create_foreign_key(
        "fk_userRole_org_role_tenant",
        "userRole",
        "role",
        ["organizationId", "roleId"],
        ["organizationId", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_userRole_org_role_tenant", "userRole", type_="foreignkey")
    op.drop_constraint("uq_role_org_id", "role", type_="unique")
