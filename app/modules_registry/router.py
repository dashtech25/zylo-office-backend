import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.identity.permissions import ORGANIZATION_MANAGE
from app.modules_registry import service
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.permissions import MODULE_MANAGE
from app.modules_registry.schemas import ActivateModuleRequest, ModuleResponse, OrganizationModuleResponse
from app.rbac.service import require_permission

router = APIRouter()


@router.get("", response_model=list[ModuleResponse])
async def list_modules(db: AsyncSession = Depends(get_db)) -> list[Module]:
    result = await db.execute(select(Module))
    return list(result.scalars().all())


@router.post(
    "/organizations/{organization_id}/activate",
    response_model=OrganizationModuleResponse,
    dependencies=[Depends(require_permission(MODULE_MANAGE))],
)
async def activate(
    organization_id: uuid.UUID, data: ActivateModuleRequest, db: AsyncSession = Depends(get_db)
) -> OrganizationModule:
    return await service.activate_module(db, organization_id, data.moduleCode)


@router.post(
    "/organizations/{organization_id}/deactivate",
    response_model=OrganizationModuleResponse,
    dependencies=[Depends(require_permission(MODULE_MANAGE))],
)
async def deactivate(
    organization_id: uuid.UUID, data: ActivateModuleRequest, db: AsyncSession = Depends(get_db)
) -> OrganizationModule:
    return await service.deactivate_module(db, organization_id, data.moduleCode)


@router.get(
    "/organizations/{organization_id}/zylo-liquid/protected-demo",
    dependencies=[Depends(require_permission(ORGANIZATION_MANAGE)), Depends(service.require_module_active("zylo_liquid"))],
)
async def protected_demo(organization_id: uuid.UUID) -> dict[str, str]:
    """Démonstration Phase 7 — même utilisateur, même permission accordée,
    mais l'accès dépend en plus du statut d'activation du module zylo_liquid
    pour l'organisation courante (X-Organization-Id)."""
    return {"status": "accès autorisé", "module": "zylo_liquid"}
