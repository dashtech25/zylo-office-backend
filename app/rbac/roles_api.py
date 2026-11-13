"""Rôles et attribution sur l'organisation courante (BE-190, QE-API-01).

Routes publiques, montées sous `/api/v1/roles` par `app/api/v1/router.py` :

- `GET /api/v1/roles` : rôles de l'organisation courante, sans leurs permissions.
- `POST /api/v1/roles` : déclare un rôle avec ses codes de permission. Un code absent
  du catalogue (`permission`) est refusé 422 `permission_unknown` (CA-3).
- `POST /api/v1/roles/{role_id}/grants` : attribue ce rôle à un membre de l'organisation
  courante, éventuellement sur une ressource (corps : `userId`, `resourceType`?, `resourceId`?).

Intention : ces routes ne font que valider la requête HTTP. Les règles métier restent dans
`app/rbac/service.py` (`create_role`, `assign_role`, `get_role`) : aucun second chemin de
décision n'est créé ici.

Organisation : résolue par l'en-tête `X-Organization-Id` via `get_current_organization_id`.
Un non-membre reçoit l'erreur de garde de `app/rbac/guards.py`. Un rôle d'une autre
organisation renvoie 404 `role_not_found` (`service.get_role`), jamais 403, pour ne pas
révéler son existence (CA-2).

Permission : `rbac.role.manage` (ROLE_MANAGE), vérifiée avant toute écriture (403
`permission_denied`). Un appel direct sans grant échoue donc côté serveur, même si
l'interface masque le bouton (CA-1, CA-6).

Permission plateforme : tout code `platform.*` est réservé à la plateforme (attribué par
allowlist d'environnement, voir `app/tenants/permissions.py`). Un rôle client ne peut ni
déclarer, ni attribuer un rôle qui en contient une : 403 `platform_permission_denied`, sans
écriture (CA-4). Le refus est inconditionnel sur ces routes : aucune exception n'est accordée
par un rôle, même si le créateur possède la permission par ailleurs.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac import service
from app.rbac.guards import get_current_organization_id
from app.rbac.models import Permission
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.schemas import CreateRoleRequest, RoleResponse, UserRoleResponse
from app.rbac.service import require_permission

router = APIRouter()

PREFIXE_PLATEFORME = "platform."


class AttributionRoleRequest(BaseModel):
    """Membre visé par l'attribution et portée facultative. `resourceType`/`resourceId`
    suivent la convention de `UserRole` (ex. `station` + identifiant)."""

    userId: uuid.UUID
    resourceType: str | None = None
    resourceId: uuid.UUID | None = None


async def _assert_codes_connus(db: AsyncSession, codes: list[str]) -> None:
    """Refuse 422 `permission_unknown` si un code ne figure pas au catalogue `permission`.

    Un code inconnu n'est jamais créé à la volée : la déclaration d'une permission
    appartient au module qui la porte (`get_or_create_permission`), pas à une requête de rôle.
    """
    if not codes:
        return
    connus = set((await db.execute(select(Permission.code).where(Permission.code.in_(codes)))).scalars().all())
    inconnus = sorted(set(codes) - connus)
    if inconnus:
        raise AppError(
            code="permission_unknown",
            message=f"Permission inconnue : {', '.join(inconnus)}.",
            status_code=422,
        )


def _assert_pas_de_permission_plateforme(codes: list[str]) -> None:
    """Refuse 403 `platform_permission_denied` si un code relève de la plateforme (CA-4)."""
    plateforme = [code for code in codes if code.startswith(PREFIXE_PLATEFORME)]
    if plateforme:
        raise AppError(
            code="platform_permission_denied",
            message=f"Un rôle client ne peut pas accorder une permission plateforme : {', '.join(plateforme)}.",
            status_code=403,
        )


@router.get(
    "",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
    summary="Lister les rôles de l'organisation courante (BE-190)",
)
async def lister_roles(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie les rôles de l'organisation courante et uniquement ceux-là (isolation tenant).

    Refus : 403 `permission_denied` sans `rbac.role.manage` ; 404 si l'en-tête désigne une
    organisation dont l'utilisateur n'est pas membre actif.
    """
    return await service.list_roles(db, organization_id)


@router.post(
    "",
    response_model=RoleResponse,
    status_code=201,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
    summary="Déclarer un rôle de l'organisation courante (BE-190)",
)
async def declarer_role(
    data: CreateRoleRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crée un rôle avec ses permissions, bornées par la non-élévation du créateur (service).

    Refus : 403 `permission_denied` sans `rbac.role.manage` ; 422 `permission_unknown` si un
    code n'est pas au catalogue (CA-3) ; 403 `platform_permission_denied` si un code est
    plateforme (CA-4).
    """
    await _assert_codes_connus(db, data.permissionCodes)
    _assert_pas_de_permission_plateforme(data.permissionCodes)
    return await service.create_role(
        db, organization_id, current_user.id, data.code, data.name, data.permissionCodes
    )


@router.post(
    "/{role_id}/grants",
    response_model=UserRoleResponse,
    status_code=201,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
    summary="Attribuer un rôle à un membre de l'organisation courante (BE-190)",
)
async def attribuer_role(
    role_id: uuid.UUID,
    data: AttributionRoleRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attribue `role_id` au membre `userId`, sur la portée donnée (ou l'organisation entière).

    Ordre des contrôles : permission `rbac.role.manage` (403) ; rôle de l'organisation courante
    (404, CA-2) ; aucune permission plateforme dans le rôle (403, CA-4) ; puis la règle de
    `service.assign_role` (non-élévation, doublon, audit `rbac.role.assign` dans la même
    transaction, CA-5).
    """
    role = await service.get_role(db, organization_id, role_id)
    codes_du_role = await service.get_role_permission_codes(db, role.id)
    _assert_pas_de_permission_plateforme(codes_du_role)
    return await service.assign_role(
        db,
        organization_id,
        current_user.id,
        data.userId,
        role.id,
        data.resourceType,
        data.resourceId,
    )
