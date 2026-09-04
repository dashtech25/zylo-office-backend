import uuid
from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.schemas import InstalledModuleResponse
from app.rbac.models import Permission, Role, RolePermission
from app.rbac.service import get_current_organization_id


async def grant_module_permissions_to_owner(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> None:
    """Sans cet appel, aucune permission déclarée par un module n'est
    accordable après son activation : aucun endpoint HTTP de gestion des
    rôles n'existe encore dans le socle (constat fait à la construction de
    l'endpoint 1 de Zylo Liquid, issue #23) — le owner doit donc recevoir de
    plein droit les permissions du module qu'il vient d'activer pour son
    organisation, exactement comme il reçoit déjà celles du socle à la
    création de l'organisation (OWNER_DEFAULT_PERMISSIONS, identity/service.py)."""
    result = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == "owner"))
    owner_role = result.scalar_one_or_none()
    if owner_role is None:
        return

    permissions = (await db.execute(select(Permission).where(Permission.moduleCode == module_code))).scalars().all()
    if not permissions:
        return

    existing = (
        (
            await db.execute(
                select(RolePermission.permissionId).where(RolePermission.roleId == owner_role.id)
            )
        )
        .scalars()
        .all()
    )
    existing_ids = set(existing)
    for permission in permissions:
        if permission.id not in existing_ids:
            db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))


async def get_or_create_module(db: AsyncSession, code: str, name: str, description: str, version: str = "0.1.0") -> Module:
    result = await db.execute(select(Module).where(Module.code == code))
    module = result.scalar_one_or_none()
    if module:
        return module
    module = Module(code=code, name=name, description=description, version=version)
    db.add(module)
    await db.flush()
    return module


async def activate_module(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> OrganizationModule:
    result = await db.execute(select(Module).where(Module.code == module_code))
    if result.scalar_one_or_none() is None:
        raise AppError(code="module_not_found", message=f"Module inconnu : {module_code}.", status_code=404)

    result = await db.execute(
        select(OrganizationModule).where(
            OrganizationModule.organizationId == organization_id, OrganizationModule.moduleCode == module_code
        )
    )
    org_module = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if org_module is None:
        org_module = OrganizationModule(
            organizationId=organization_id, moduleCode=module_code, status="active", activatedAt=now
        )
        db.add(org_module)
    else:
        org_module.status = "active"
        org_module.activatedAt = now
        org_module.deactivatedAt = None
    await grant_module_permissions_to_owner(db, organization_id, module_code)
    await db.commit()
    await db.refresh(org_module)
    return org_module


async def deactivate_module(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> OrganizationModule:
    result = await db.execute(
        select(OrganizationModule).where(
            OrganizationModule.organizationId == organization_id, OrganizationModule.moduleCode == module_code
        )
    )
    org_module = result.scalar_one_or_none()
    if org_module is None:
        raise AppError(code="module_not_activated", message="Ce module n'est pas activé pour cette organisation.", status_code=404)
    org_module.status = "inactive"
    org_module.deactivatedAt = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(org_module)
    return org_module


async def is_module_active(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> bool:
    result = await db.execute(
        select(OrganizationModule.status).where(
            OrganizationModule.organizationId == organization_id,
            OrganizationModule.moduleCode == module_code,
        )
    )
    status_value = result.scalar_one_or_none()
    return status_value in ("active", "trial")


async def list_installed_modules(db: AsyncSession, organization_id: uuid.UUID) -> list[InstalledModuleResponse]:
    """Croise le catalogue complet des modules avec les activations de
    l'organisation — 'inactive' par défaut si aucune ligne OrganizationModule
    n'existe pour ce module (jamais activé pour cette organisation)."""
    modules = (await db.execute(select(Module).order_by(Module.name))).scalars().all()
    org_modules = (
        (await db.execute(select(OrganizationModule).where(OrganizationModule.organizationId == organization_id)))
        .scalars()
        .all()
    )
    org_modules_by_code = {org_module.moduleCode: org_module for org_module in org_modules}

    result: list[InstalledModuleResponse] = []
    for module in modules:
        org_module = org_modules_by_code.get(module.code)
        result.append(
            InstalledModuleResponse(
                moduleCode=module.code,
                name=module.name,
                description=module.description,
                version=module.version,
                status=org_module.status if org_module else "inactive",
                activatedAt=org_module.activatedAt if org_module else None,
            )
        )
    return result


def require_module_active(module_code: str):
    """Combinable avec require_permission() sur une même route — un module
    inactif bloque l'accès même si l'utilisateur a la permission requise
    (grande_phases.md §9)."""

    async def dependency(
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not await is_module_active(db, organization_id, module_code):
            raise AppError(
                code="module_inactive",
                message=f"Le module '{module_code}' n'est pas actif pour cette organisation.",
                status_code=403,
            )

    return dependency
