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
    ModuleAccessResponse,
    ModuleResponse,
    OrganizationModuleResponse,
    SetModuleActivationRequest,
)
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter()

# Routes du catalogue rattachées à l'organisation courante (BE-022), montées sous `/organizations` :
# l'organisation est choisie par l'en-tête `X-Organization-Id`, validée par l'appartenance active.
organizations_modules_router = APIRouter()


@organizations_modules_router.get(
    "/current/modules",
    response_model=list[InstalledModuleResponse],
    summary="Catalogue des modules avec leur état d'activation pour l'organisation courante",
)
async def list_current_organization_modules(
    organization_id: uuid.UUID = Depends(get_current_organization_id), db: AsyncSession = Depends(get_db)
) -> list[InstalledModuleResponse]:
    """Lecture ouverte à tout membre actif de l'organisation courante. Un non-membre ne reçoit
    jamais le catalogue (refus par `get_current_organization_id`)."""
    return await service.list_installed_modules(db, organization_id)


@organizations_modules_router.get(
    "/current/modules/{module_id}/access",
    response_model=ModuleAccessResponse,
    summary="Projection d'accès (canOpen / canActivate) d'un module pour l'organisation courante",
)
async def get_current_organization_module_access(
    module_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ModuleAccessResponse:
    """Lecture ouverte à tout membre actif de l'organisation courante (BE-025). Les droits sont
    calculés côté serveur : `canOpen` est faux pour `inactive`, `expired` et `blocked` (comme pour
    un module non activé ou au manifeste incompatible) ; la garde réelle reste celle des routes du
    module, qui répond 403. 404 si le module n'existe pas au catalogue."""
    return await service.get_module_access_projection(db, organization_id, module_id)


@organizations_modules_router.put(
    "/current/modules/{module_id}/activation",
    response_model=OrganizationModuleResponse,
    summary="Activer ou désactiver un module pour l'organisation courante",
    dependencies=[Depends(require_permission(MODULE_MANAGE))],
)
async def set_current_organization_module_activation(
    module_id: uuid.UUID,
    data: SetModuleActivationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationModule:
    """Active (`active: true`) ou désactive (`active: false`) le module `module_id` du catalogue.

    Exige la permission `modules.module.manage` (403 sinon, sans modification). Module absent du
    catalogue ou inconnu de l'application : 404. Module `incompatible` : 409, activation seulement.
    Chaque transition écrit une entrée d'audit et ne touche qu'à l'organisation courante.
    """
    return await service.set_module_activation(db, organization_id, current_user.id, module_id, data.active)


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
