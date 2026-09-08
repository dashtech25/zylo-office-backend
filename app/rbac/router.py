import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.rbac import service
from app.rbac.models import Permission
from app.rbac.permissions import GRANT_MANAGE, ROLE_MANAGE
from app.rbac.schemas import (
    AssignRoleRequest,
    CreateGrantRequest,
    CreateRoleRequest,
    GrantResponse,
    OrganizationMemberResponse,
    PermissionResponse,
    RoleDetailResponse,
    RoleResponse,
    UpdateRolePermissionsRequest,
    UserRoleResponse,
)
from app.rbac.service import require_permission

router = APIRouter()


@router.get(
    "/organizations/{organization_id}/permissions",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_permissions_catalog(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[Permission]:
    """Catalogue complet des permissions connues, groupable par module côté
    frontend (§14.2 : présentation par module puis par famille)."""
    result = await db.execute(select(Permission).order_by(Permission.moduleCode, Permission.code))
    return list(result.scalars().all())


@router.get(
    "/organizations/{organization_id}/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_roles(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_roles(db, organization_id)


@router.get(
    "/organizations/{organization_id}/roles/{role_id}",
    response_model=RoleDetailResponse,
    dependencies=[Depends(require_organization_member)],
)
async def get_role(organization_id: uuid.UUID, role_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    role = await service.get_role(db, organization_id, role_id)
    codes = await service.get_role_permission_codes(db, role.id)
    return RoleDetailResponse(id=role.id, organizationId=role.organizationId, code=role.code, name=role.name, permissionCodes=codes)


@router.post(
    "/organizations/{organization_id}/roles",
    response_model=RoleResponse,
    status_code=201,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
)
async def create_role(
    organization_id: uuid.UUID,
    data: CreateRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_role(db, organization_id, current_user.id, data.code, data.name, data.permissionCodes)


@router.put(
    "/organizations/{organization_id}/roles/{role_id}/permissions",
    response_model=RoleDetailResponse,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
)
async def update_role_permissions(
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    data: UpdateRolePermissionsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = await service.update_role_permissions(db, organization_id, current_user.id, role_id, data.permissionCodes)
    codes = await service.get_role_permission_codes(db, role.id)
    return RoleDetailResponse(id=role.id, organizationId=role.organizationId, code=role.code, name=role.name, permissionCodes=codes)


@router.post(
    "/organizations/{organization_id}/user-roles",
    response_model=UserRoleResponse,
    status_code=201,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
)
async def assign_role(
    organization_id: uuid.UUID,
    data: AssignRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.assign_role(
        db, organization_id, current_user.id, data.userId, data.roleId, data.resourceType, data.resourceId
    )


@router.delete(
    "/organizations/{organization_id}/user-roles/{assignment_id}",
    status_code=204,
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
)
async def unassign_role(
    organization_id: uuid.UUID,
    assignment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.unassign_role(db, organization_id, current_user.id, assignment_id)


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMemberResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_members(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_organization_members_with_roles(db, organization_id)


@router.get(
    "/organizations/{organization_id}/users/{user_id}/grants",
    response_model=list[GrantResponse],
    dependencies=[Depends(require_permission(GRANT_MANAGE))],
)
async def list_user_grants(organization_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_user_grants(db, organization_id, user_id)


@router.post(
    "/organizations/{organization_id}/grants",
    response_model=GrantResponse,
    status_code=201,
    dependencies=[Depends(require_permission(GRANT_MANAGE))],
)
async def create_grant(
    organization_id: uuid.UUID,
    data: CreateGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_grant(
        db,
        organization_id,
        current_user.id,
        data.userId,
        data.permissionCode,
        data.effect,
        resource_type=data.resourceType,
        resource_id=data.resourceId,
        valid_until=data.validUntil,
        audit_note=data.auditNote,
        delegated_from_grant_id=data.delegatedFromGrantId,
    )


@router.delete(
    "/organizations/{organization_id}/grants/{grant_id}",
    status_code=204,
    dependencies=[Depends(require_permission(GRANT_MANAGE))],
)
async def revoke_grant(
    organization_id: uuid.UUID,
    grant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.revoke_grant(db, organization_id, current_user.id, grant_id)


@router.get(
    "/organizations/{organization_id}/me/permissions",
    response_model=list[str],
    dependencies=[Depends(require_organization_member)],
)
async def my_effective_permissions(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Consommé par le frontend pour conditionner l'affichage (§20 : jamais
    un substitut à la vérification serveur, seulement une anticipation
    ergonomique du résultat)."""
    return await service.list_effective_permission_codes(db, organization_id, current_user.id)
