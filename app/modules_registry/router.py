import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.service import require_organization_member
from app.modules_registry import service
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.permissions import MODULE_MANAGE
from app.modules_registry.schemas import (
    ActivateModuleRequest,
    InstalledModuleResponse,
    ModuleResponse,
    OrganizationModuleResponse,
)
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter()


@router.get("", response_model=Page[ModuleResponse])
async def list_modules(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)) -> Page:
    return await paginate(db, select(Module).order_by(Module.code), pagination, ModuleResponse)


@router.get(
    "/organizations/{organization_id}",
    response_model=list[InstalledModuleResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_organization_modules(
    organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[InstalledModuleResponse]:
    return await service.list_installed_modules(db, organization_id)


@router.post(
    "/organizations/{organization_id}/activate",
    response_model=OrganizationModuleResponse,
    dependencies=[Depends(require_permission(MODULE_MANAGE))],
)
async def activate(
    organization_id: uuid.UUID,
    data: ActivateModuleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationModule:
    return await service.activate_module(db, organization_id, current_user.id, data.moduleCode)


@router.post(
    "/organizations/{organization_id}/deactivate",
    response_model=OrganizationModuleResponse,
    dependencies=[Depends(require_permission(MODULE_MANAGE))],
)
async def deactivate(
    organization_id: uuid.UUID,
    data: ActivateModuleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationModule:
    return await service.deactivate_module(db, organization_id, current_user.id, data.moduleCode)


@router.get(
    "/organizations/{organization_id}/zylo-liquid/protected-demo",
    dependencies=[Depends(require_permission(ORGANIZATION_MANAGE)), Depends(service.require_module_active("zylo_liquid"))],
)
async def protected_demo(organization_id: uuid.UUID) -> dict[str, str]:
    """Démonstration Phase 7 — même utilisateur, même permission accordée,
    mais l'accès dépend en plus du statut d'activation du module zylo_liquid
    pour l'organisation courante (X-Organization-Id)."""
    return {"status": "accès autorisé", "module": "zylo_liquid"}
