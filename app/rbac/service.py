import uuid

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.models import Permission, Role, RolePermission, UserRole


async def get_current_organization_id(
    x_organization_id: uuid.UUID = Header(..., alias="X-Organization-Id"),
) -> uuid.UUID:
    """L'organisation courante est portée par le header X-Organization-Id — un
    utilisateur pouvant appartenir à plusieurs organisations, elle ne peut pas
    être déduite du seul token JWT."""
    return x_organization_id


async def user_has_permission(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, permission_code: str
) -> bool:
    stmt = (
        select(Permission.id)
        .join(RolePermission, RolePermission.permissionId == Permission.id)
        .join(Role, Role.id == RolePermission.roleId)
        .join(UserRole, UserRole.roleId == Role.id)
        .where(
            UserRole.userId == user_id,
            UserRole.organizationId == organization_id,
            Role.organizationId == organization_id,
            Permission.code == permission_code,
        )
    )
    result = await db.execute(stmt)
    return result.first() is not None


def require_permission(permission_code: str):
    """Dépendance FastAPI générique — un module déclare simplement
    `Depends(require_permission("crm.contact.read"))` sur sa route, sans jamais
    dupliquer la logique d'autorisation (grande_phases.md §8)."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        allowed = await user_has_permission(db, current_user.id, organization_id, permission_code)
        if not allowed:
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {permission_code}.",
                status_code=403,
            )

    return dependency


async def get_or_create_permission(db: AsyncSession, code: str, module_code: str, description: str) -> Permission:
    result = await db.execute(select(Permission).where(Permission.code == code))
    permission = result.scalar_one_or_none()
    if permission:
        return permission
    permission = Permission(code=code, moduleCode=module_code, description=description)
    db.add(permission)
    await db.flush()
    return permission
