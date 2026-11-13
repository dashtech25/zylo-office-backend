"""Lecture des rôles de l'organisation courante (BE-016).

Routes publiques, montées sous `/api/v1/organizations` par `app/api/v1/router.py` :

- `GET /api/v1/organizations/current/roles` : liste des rôles de l'organisation.
- `GET /api/v1/organizations/current/roles/{roleId}` : détail d'un rôle et de ses
  codes de permission.

Ces routes sont en lecture seule : toute écriture sur ces chemins (PUT, PATCH,
DELETE) répond 405, les écritures restant sur les routes de `app/rbac/router.py`.

Organisation : résolue par l'en-tête `X-Organization-Id` via
`get_current_organization_id` (même sélecteur que `GET /organizations/current`).
Un non-membre reçoit l'erreur de garde de `app/rbac/guards.py`.

Permission : provisoirement `rbac.role.manage` (ROLE_MANAGE), déjà accordée au
propriétaire. Le code de lecture est NON DÉFINI (QE-SOC-06) ; il n'est pas ajouté
au rôle propriétaire pour ne pas changer le nombre de ses 12 permissions (CA-1).

Isolation : un rôle est cherché dans l'organisation courante seulement ; un rôle
d'une autre organisation renvoie 404 `role_not_found` (`service.get_role`).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.rbac import service
from app.rbac.guards import get_current_organization_id
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.schemas import RoleDetailResponse, RoleResponse
from app.rbac.service import require_permission

router = APIRouter()


@router.get(
    "/current/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
    summary="Lister les rôles de l'organisation courante",
)
async def lister_roles(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie les rôles de l'organisation courante, sans leurs permissions.

    Refus : 403 `permission_denied` si le membre n'a pas la permission de lecture
    des rôles ; 404 si l'en-tête désigne une organisation dont l'utilisateur n'est
    pas membre actif.
    """
    return await service.list_roles(db, organization_id)


@router.get(
    "/current/roles/{role_id}",
    response_model=RoleDetailResponse,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
    summary="Lire un rôle de l'organisation courante avec ses permissions",
)
async def lire_role(
    role_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie un rôle et la liste de ses codes de permission.

    Refus : 403 sans permission de lecture ; 404 `role_not_found` si le rôle
    n'existe pas dans l'organisation courante, y compris s'il appartient à une
    autre organisation (pas d'énumération entre tenants).
    """
    role = await service.get_role(db, organization_id, role_id)
    codes = await service.get_role_permission_codes(db, role.id)
    return RoleDetailResponse(
        id=role.id,
        organizationId=role.organizationId,
        code=role.code,
        name=role.name,
        moduleCode=role.moduleCode,
        permissionCodes=codes,
    )
