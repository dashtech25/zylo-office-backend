import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.service import require_organization_member
from app.core.idempotency import require_idempotency_key, run_idempotent
from app.modules_registry import declarations, installation, mise_a_jour, service
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.permissions import (
    MODULE_MANAGE,
    ORGANIZATION_MODULE_INSTALL,
    ORGANIZATION_MODULE_READ,
    ORGANIZATION_MODULE_UPGRADE,
)
from app.modules_registry.schemas import (
    ActivateModuleRequest,
    InstallModuleRequest,
    InstalledModuleResponse,
    ModuleAccessResponse,
    ModuleInstallationResponse,
    UpgradeModuleRequest,
    ModulePermissionResponse,
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


@organizations_modules_router.get(
    "/{organization_id}/modules/{module_id}/permissions",
    response_model=list[ModulePermissionResponse],
    summary="Permissions déclarées par la version installée d'un module (BE-055)",
    dependencies=[Depends(require_permission(ORGANIZATION_MODULE_READ))],
)
async def list_module_permissions(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ModulePermissionResponse]:
    """Liste les permissions déclarées par la version installée du module `module_id`, triées par code.

    Exige `organization.module.read` sur l'organisation du chemin : 403 sans elle, 404 pour une
    organisation d'un autre tenant (la garde de `require_permission` répond avant la route).
    Lecture seule : aucune donnée d'une autre organisation n'est renvoyée, puisque la liste ne
    dépend que du catalogue. 404 si le module est inconnu ou sans version installée.
    """
    lignes = await declarations.lister_permissions_installees(db, module_id)
    return [ModulePermissionResponse.model_validate(ligne) for ligne in lignes]


@organizations_modules_router.post(
    "/{organization_id}/modules/{module_id}/installations",
    summary="Installer techniquement un module pour une organisation (BE-047)",
    dependencies=[Depends(require_permission(ORGANIZATION_MODULE_INSTALL))],
)
async def installer_module(
    organization_id: uuid.UUID,
    module_id: uuid.UUID,
    data: InstallModuleRequest,
    request: Request,
    cle: str = Depends(require_idempotency_key),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Crée l'installation de la version `moduleVersionId` et la mène à `installed` (ou `failed`).

    Exige `organization.module.install` sur l'organisation du chemin (403 sinon, sans ligne créée).
    L'en-tête `Idempotency-Key` est obligatoire : le même couple (clé, charge) renvoie la réponse
    initiale avec le même `operationId`, sans seconde installation (`core/idempotency`).
    Refus préalables (détaillés dans `modules_registry/installation.py`) : 422
    `MODULE_VERSION_NOT_PUBLISHED`, 409 `MODULE_VERSION_INCOMPATIBLE`, 409
    `MODULE_PREREQUISITE_MISSING`, 409 `MODULE_ALREADY_INSTALLED`. Un échec de provisionnement ne
    fait pas échouer la requête : la réponse 201 porte l'état `failed` et son `lastErrorCode`.
    """

    async def produire() -> tuple[int, dict]:
        ligne = await installation.executer_installation(
            db,
            organization_id=organization_id,
            acteur_id=current_user.id,
            module_id=module_id,
            module_version_id=data.moduleVersionId,
            state_version=data.stateVersion,
            cle_idempotence=cle,
        )
        return 201, ModuleInstallationResponse.model_validate(ligne).model_dump(mode="json")

    resultat = await run_idempotent(
        db,
        cle=cle,
        organisation_id=organization_id,
        acteur_id=current_user.id,
        methode=request.method,
        chemin=request.url.path,
        charge=data.model_dump(mode="json"),
        produire=produire,
    )
    return JSONResponse(status_code=resultat.statut, content=resultat.corps)


@organizations_modules_router.post(
    "/{organization_id}/modules/{module_id}/upgrades",
    summary="Mettre à jour une installation vers une version cible rN+1 (BE-051)",
    dependencies=[Depends(require_permission(ORGANIZATION_MODULE_UPGRADE))],
)
async def mettre_a_jour_module(
    organization_id: uuid.UUID,
    module_id: uuid.UUID,
    data: UpgradeModuleRequest,
    request: Request,
    cle: str = Depends(require_idempotency_key),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Fait passer l'installation de l'organisation à `targetModuleVersionId` (BE-051).

    Exige `organization.module.upgrade` sur l'organisation du chemin (403 sinon, sans changement).
    L'en-tête `Idempotency-Key` est obligatoire ; un rejeu avec la même clé renvoie la réponse
    initiale sans seconde mise à jour (`core/idempotency`). Refus préalables (détaillés dans
    `modules_registry/mise_a_jour.py`) : 404 installation absente, 409 `MODULE_STATE_VERSION_CONFLICT`,
    422 `MODULE_VERSION_NOT_PUBLISHED`, 409 `MODULE_UPGRADE_NOT_ALLOWED` (plan absent ou cible
    incompatible), 409 `MODULE_UPGRADE_FORWARD_ONLY`. Un échec de migration ne fait pas échouer la
    requête : la réponse 200 porte `upgradeState = failed`, `lastErrorCode` et la version source.
    """

    async def produire() -> tuple[int, dict]:
        ligne = await mise_a_jour.executer_mise_a_jour(
            db,
            organization_id=organization_id,
            acteur_id=current_user.id,
            module_id=module_id,
            target_module_version_id=data.targetModuleVersionId,
            state_version=data.stateVersion,
            cle_idempotence=cle,
            confirmation_forward_only=data.confirmationForwardOnly,
        )
        return 200, ModuleInstallationResponse.model_validate(ligne).model_dump(mode="json")

    resultat = await run_idempotent(
        db,
        cle=cle,
        organisation_id=organization_id,
        acteur_id=current_user.id,
        methode=request.method,
        chemin=request.url.path,
        charge=data.model_dump(mode="json"),
        produire=produire,
    )
    return JSONResponse(status_code=resultat.statut, content=resultat.corps)


@organizations_modules_router.get(
    "/{organization_id}/modules/{module_id}/installations/{operation_id}",
    response_model=ModuleInstallationResponse,
    summary="Relire une opération d'installation (BE-047)",
    dependencies=[Depends(require_permission(ORGANIZATION_MODULE_INSTALL))],
)
async def lire_operation_installation(
    organization_id: uuid.UUID,
    module_id: uuid.UUID,
    operation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ModuleInstallationResponse:
    """Renvoie l'état courant de l'opération `operation_id` (cas d'un résultat incertain).

    404 si l'opération n'existe pas pour ce couple (organisation, module), y compris pour une
    opération d'une autre organisation."""
    ligne = await installation.lire_installation_par_operation(db, organization_id, module_id, operation_id)
    return ModuleInstallationResponse.model_validate(ligne)


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
