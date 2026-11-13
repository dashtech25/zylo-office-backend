"""Endpoints des rôles de module (T-018).

Intention : chaque route vérifie D'ABORD que le chemin `organization_id` est
celui de l'en-tête `X-Organization-Id` (sinon 403). Sans ce contrôle, un
utilisateur autorisé dans son organisation pourrait agir sur une autre en
changeant le chemin (défaut IAM-001, corrigé globalement par T-010 : ce
contrôle local reste en place, il ne dépend pas de cette correction).
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import OrganizationUser, User
from app.identity.service import require_organization_member
from app.rbac.models import Role
from app.rbac.module_affectation import (
    definir_role_module,
    lister_membres_module,
    previsualiser_changement_module,
    retirer_role_module,
)
from app.rbac.module_assignment import assign_module_role, create_module_role, unassign_module_role
from app.rbac.module_rights import effective_rights_by_module
from app.rbac.module_schemas import (
    ModuleMemberItem,
    ModuleRightsItem,
    ModuleRolePreviewResponse,
    ModuleRoleAssignmentResponse,
    ModuleRoleAssignRequest,
    ModuleRoleCreateRequest,
    ModuleRoleResponse,
    ModuleRoleSetRequest,
)
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.service import get_current_organization_id, require_permission, user_has_permission

router = APIRouter()


async def _ensure_path_matches_header(
    organization_id: uuid.UUID,
    header_organization_id: uuid.UUID = Depends(get_current_organization_id),
) -> None:
    if organization_id != header_organization_id:
        raise AppError(
            code="organization_mismatch",
            message="L'organisation du chemin ne correspond pas à l'en-tête X-Organization-Id.",
            status_code=403,
        )


GUARD = Depends(_ensure_path_matches_header)


@router.post(
    "/organizations/{organization_id}/module-roles",
    response_model=ModuleRoleResponse,
    status_code=201,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def create_module_role_endpoint(
    organization_id: uuid.UUID,
    data: ModuleRoleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = await create_module_role(
        db, organization_id, current_user.id, data.moduleCode, data.code, data.name, data.permissionCodes
    )
    return ModuleRoleResponse(
        id=role.id, organizationId=role.organizationId, moduleCode=role.moduleCode, code=role.code, name=role.name
    )


@router.post(
    "/organizations/{organization_id}/module-roles/assignments",
    response_model=ModuleRoleAssignmentResponse,
    status_code=201,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def assign_module_role_endpoint(
    organization_id: uuid.UUID,
    data: ModuleRoleAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_role = await assign_module_role(db, organization_id, current_user.id, data.userId, data.roleId)
    role = await db.get(Role, user_role.roleId)
    return ModuleRoleAssignmentResponse(
        assignmentId=user_role.id,
        userId=user_role.userId,
        organizationId=user_role.organizationId,
        roleId=role.id,
        moduleCode=role.moduleCode,
        roleCode=role.code,
        roleName=role.name,
    )


@router.delete(
    "/organizations/{organization_id}/module-roles/assignments/{assignment_id}",
    status_code=204,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def unassign_module_role_endpoint(
    organization_id: uuid.UUID,
    assignment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await unassign_module_role(db, organization_id, current_user.id, assignment_id)


@router.get(
    "/organizations/{organization_id}/users/{user_id}/module-rights",
    response_model=list[ModuleRightsItem],
    dependencies=[GUARD, Depends(require_organization_member)],
)
async def list_module_rights(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Un utilisateur voit ses propres droits ; voir ceux d'un autre exige ROLE_MANAGE."""
    if user_id != current_user.id and not await user_has_permission(db, current_user.id, organization_id, ROLE_MANAGE):
        raise AppError(code="permission_denied", message=f"Permission manquante : {ROLE_MANAGE}.", status_code=403)
    membership = await db.execute(
        select(OrganizationUser.id).where(OrganizationUser.organizationId == organization_id, OrganizationUser.userId == user_id)
    )
    if membership.scalar_one_or_none() is None:
        # On ne révèle ni les modules ni les droits d'un utilisateur hors de l'organisation.
        raise AppError(code="user_not_member", message="Cet utilisateur n'est pas membre de l'organisation.", status_code=404)
    return await effective_rights_by_module(db, organization_id, user_id)


# ---------------------------------------------------------------------------
# Affectation par module (T-022) : un rôle par utilisateur et par module.
# Intention : l'administrateur raisonne en « module » (membre -> rôle du module),
# pas en identifiant d'affectation. Toutes les règles sont dans module_affectation.py.
# ---------------------------------------------------------------------------


@router.get(
    "/organizations/{organization_id}/modules/{module_code}/members",
    response_model=list[ModuleMemberItem],
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def list_module_members_endpoint(
    organization_id: uuid.UUID,
    module_code: str,
    db: AsyncSession = Depends(get_db),
):
    return await lister_membres_module(db, organization_id, module_code)


@router.put(
    "/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role",
    response_model=ModuleRoleAssignmentResponse,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def set_module_role_endpoint(
    organization_id: uuid.UUID,
    module_code: str,
    user_id: uuid.UUID,
    data: ModuleRoleSetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_role = await definir_role_module(db, organization_id, current_user.id, module_code, user_id, data.roleId)
    role = await db.get(Role, user_role.roleId)
    return ModuleRoleAssignmentResponse(
        assignmentId=user_role.id,
        userId=user_role.userId,
        organizationId=user_role.organizationId,
        roleId=role.id,
        moduleCode=role.moduleCode,
        roleCode=role.code,
        roleName=role.name,
    )


@router.delete(
    "/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role",
    status_code=204,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def clear_module_role_endpoint(
    organization_id: uuid.UUID,
    module_code: str,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await retirer_role_module(db, organization_id, current_user.id, module_code, user_id)


@router.get(
    "/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role-preview",
    response_model=ModuleRolePreviewResponse,
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def preview_module_role_endpoint(
    organization_id: uuid.UUID,
    module_code: str,
    user_id: uuid.UUID,
    role_id: uuid.UUID | None = Query(default=None, alias="roleId"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sans `roleId` : prévisualise le retrait du rôle du module."""
    return await previsualiser_changement_module(db, organization_id, current_user.id, module_code, user_id, role_id)
