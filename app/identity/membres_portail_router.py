"""Routes des membres d'organisation du portail (BE-106).

- `GET /organizations/{organization_id}/members` : liste des memberships de l'organisation du
  chemin, action `portail.membres.lire` (permission `organization.members.read`).
- `POST /organizations/{organization_id}/role-changes` : changement de rôles d'un membership,
  action `portail.membre.changer_role` (permission `rbac.role.manage`). Corps : `membershipId`,
  `roleIds`. Délègue à `rbac.affectation_membres.replace_member_roles`, qui écrit `RoleChanged`.
- `DELETE /organizations/{organization_id}/members/{membership}` : retrait d'un membership,
  action `portail.membre.retirer` (permission `organization.members.remove`). Délègue à
  `identity.membres.remove_member`, qui écrit `Removed`.

Réponses communes : 401 sans session ; 404 hors appartenance ou organisation inconnue, et
`membership_not_found` pour un membership qui n'appartient pas à l'organisation du chemin ;
403 sans la permission. Le membership est toujours résolu dans l'organisation du chemin : un
identifiant venant d'une autre organisation ne peut donc pas être atteint.

Montées sous `/api/v1/organizations` (app/api/v1/router.py), après le routeur `/current`, qui
garde la priorité sur le segment littéral `current`.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.identity import membres
from app.identity.models import OrganizationUser, User
from app.identity.schemas import ChangeMemberRolesRequest
from app.rbac import affectation_membres
from app.rbac.portee_organisation import OrgScope, exiger_action
from app.rbac.schemas import OrganizationMemberResponse

router = APIRouter()

PORTAIL_MEMBRES_LIRE = "portail.membres.lire"
PORTAIL_MEMBRE_CHANGER_ROLE = "portail.membre.changer_role"
PORTAIL_MEMBRE_RETIRER = "portail.membre.retirer"


async def _utilisateur_du_membership(db: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID) -> uuid.UUID:
    """Identifiant de l'utilisateur du membership, s'il appartient à `organization_id`.

    Un membership d'une autre organisation, inexistant, ou un identifiant inconnu renvoient la
    même réponse 404 `membership_not_found`, sans rien révéler de l'autre organisation."""
    user_id = await db.scalar(
        select(OrganizationUser.userId).where(
            OrganizationUser.id == membership_id,
            OrganizationUser.organizationId == organization_id,
        )
    )
    if user_id is None:
        raise AppError(code="membership_not_found", message="Membre introuvable dans cette organisation.", status_code=404)
    return user_id


@router.get(
    "/{organization_id}/members",
    response_model=list[OrganizationMemberResponse],
    summary="Lister les membres de l'organisation avec leurs rôles",
)
async def list_portal_members(
    scope: OrgScope = Depends(exiger_action(PORTAIL_MEMBRES_LIRE)),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Membres de l'organisation du chemin (BE-106, CA-1). Voir `identity.membres.list_members`."""
    return await membres.list_members(db, scope.organization_id)


@router.post(
    "/{organization_id}/role-changes",
    summary="Changer les rôles d'un membre de l'organisation",
)
async def change_member_roles(
    data: ChangeMemberRolesRequest,
    scope: OrgScope = Depends(exiger_action(PORTAIL_MEMBRE_CHANGER_ROLE)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fixe l'ensemble des rôles du membership `membershipId` (BE-106, CA-2, CA-4, CA-5).

    Le dernier propriétaire ne peut pas être rétrogradé (409 `last_owner`) ; les règles et les
    écritures (`RoleChanged`, audit) sont dans `rbac.affectation_membres.replace_member_roles`."""
    user_id = await _utilisateur_du_membership(db, scope.organization_id, data.membershipId)
    acteur = await db.get(User, scope.user_id)
    return await affectation_membres.replace_member_roles(db, scope.organization_id, acteur, user_id, data.roleIds)


@router.delete(
    "/{organization_id}/members/{membership}",
    status_code=204,
    summary="Retirer un membre de l'organisation",
)
async def remove_portal_member(
    membership: uuid.UUID,
    scope: OrgScope = Depends(exiger_action(PORTAIL_MEMBRE_RETIRER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Retire le membership `membership` de l'organisation du chemin (BE-106, CA-2, CA-3).

    Le dernier propriétaire ne peut pas être retiré (409 `last_owner`) ; l'écriture de `Removed`
    et de l'audit est dans `identity.membres.remove_member`."""
    user_id = await _utilisateur_du_membership(db, scope.organization_id, membership)
    acteur = await db.get(User, scope.user_id)
    await membres.remove_member(db, scope.organization_id, acteur, user_id)
