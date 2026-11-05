"""Console plateforme du catalogue de modules (BE-042), montée sous `/api/v1/admin`.

Routes :
- `POST /modules` : crée une fiche en `draft` (droit `platform.module.write`), 201 ;
- `GET /modules/{moduleId}` : lecture plateforme (droit write ou publish), 200 ;
- `POST /modules/{moduleId}/versions` : crée une version en `draft` (droit write), 201 ;
- `POST /modules/{moduleId}/versions/{versionId}/publish` : publie (droit publish), 200 ;
- `POST /modules/{moduleId}/versions/{versionId}/compatibility-evaluations` : évalue et journalise la
  compatibilité de la version (droit publish), 201 (BE-044) ;
- `POST /modules/{moduleId}/upgrade-plans` : calcule le plan entre deux versions, sans l'exécuter
  (droit publish), 201 (BE-044).

Chaque route vérifie le droit plateforme avant toute lecture ou écriture (refus par défaut, 403
`PERMISSION_DENIED`). Sans authentification, `get_current_user` renvoie 401. Le routeur valide la
transaction après succès : `get_db` ne commit pas seul.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import correlation_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry import catalogue_publication as service
from app.modules_registry import compatibilite_service
from app.modules_registry.platform_rights import a_droit_plateforme, exiger_droit_plateforme
from app.modules_registry.permissions import PLATFORM_MODULE_PUBLISH, PLATFORM_MODULE_WRITE
from app.modules_registry.schemas import (
    CreerModuleRequest,
    CreerVersionRequest,
    ModuleAdminResponse,
    ModuleVersionAdminResponse,
    CompatibilityEvaluationResponse,
    PublierVersionRequest,
    UpgradePlanRequest,
    UpgradePlanResponse,
)

router = APIRouter(prefix="/modules", tags=["admin-modules"])


@router.post("", response_model=ModuleAdminResponse, status_code=201, summary="Crée la fiche d'un module (draft)")
async def creer_module(
    corps: CreerModuleRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ModuleAdminResponse:
    """Crée la fiche d'un module en brouillon (`draft`) depuis la console plateforme.

    Droit : permission plateforme d'écriture du module (`exiger_droit_plateforme`). Réponses : 201 à la création, 401 sans session, 403 sans droit plateforme, 422 donnée invalide.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_MODULE_WRITE)
    module = await service.creer_module(db, code=corps.code, name=corps.name, description=corps.description)
    await db.commit()
    return ModuleAdminResponse.model_validate(module)


@router.get("/{module_id}", response_model=ModuleAdminResponse, summary="Lit la fiche d'un module (plateforme)")
async def lire_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ModuleAdminResponse:
    """Lit la fiche d'un module pour la console plateforme. Réponses : 200, 401 sans session, 403 sans droit plateforme, 404 module inconnu.
    """
    if not (
        a_droit_plateforme(utilisateur.id, PLATFORM_MODULE_WRITE)
        or a_droit_plateforme(utilisateur.id, PLATFORM_MODULE_PUBLISH)
    ):
        raise AppError(code="PERMISSION_DENIED", message="Droit plateforme requis.", status_code=403)
    return ModuleAdminResponse.model_validate(await service.lire_module(db, module_id))


@router.post(
    "/{module_id}/versions",
    response_model=ModuleVersionAdminResponse,
    status_code=201,
    summary="Crée une version de module (draft)",
)
async def creer_version(
    module_id: uuid.UUID,
    corps: CreerVersionRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ModuleVersionAdminResponse:
    """Ajoute une version en brouillon à un module existant de la console plateforme. Réponses : 201, 401, 403, 404 module inconnu, 422 donnée invalide.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_MODULE_WRITE)
    ligne = await service.creer_version(
        db,
        module_id=module_id,
        version=corps.version,
        digest=corps.digest,
        provenance=corps.provenance,
        licence=corps.licence,
        compatibility=corps.compatibility,
        prerequisites=corps.prerequisites,
    )
    await db.commit()
    return ModuleVersionAdminResponse.model_validate(ligne)


@router.post(
    "/{module_id}/versions/{version_id}/publish",
    response_model=ModuleVersionAdminResponse,
    summary="Publie une version (review puis published)",
)
async def publier_version(
    module_id: uuid.UUID,
    version_id: uuid.UUID,
    corps: PublierVersionRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ModuleVersionAdminResponse:
    """Publie une version de module. La transition passe par la machine d'états des versions : une transition non permise répond 409.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_MODULE_PUBLISH)
    version = await service.lire_version(db, module_id, version_id)
    version = await service.publier_version(
        db,
        version,
        acteur_id=utilisateur.id,
        state_version=corps.stateVersion,
        cle=corps.idempotencyKey,
        correlation_id=correlation_id_ctx.get(),
    )
    await db.commit()
    return ModuleVersionAdminResponse.model_validate(version)


@router.post(
    "/{module_id}/versions/{version_id}/compatibility-evaluations",
    response_model=CompatibilityEvaluationResponse,
    status_code=201,
    summary="Évalue la compatibilité et les dépendances d'une version (BE-044)",
)
async def evaluer_compatibilite(
    module_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> CompatibilityEvaluationResponse:
    """Renvoie `compatible`, `incompatible` ou `unknown` avec ses motifs, et journalise l'évaluation.

    Droit `platform.module.publish`, vérifié avant toute lecture : un refus ne crée aucune ligne."""
    exiger_droit_plateforme(utilisateur.id, PLATFORM_MODULE_PUBLISH)
    ligne = await compatibilite_service.evaluer_version(db, module_id, version_id)
    await db.commit()
    return CompatibilityEvaluationResponse.model_validate(ligne)


@router.post(
    "/{module_id}/upgrade-plans",
    response_model=UpgradePlanResponse,
    status_code=201,
    summary="Calcule le plan de mise à jour entre deux versions, sans l'exécuter (BE-044)",
)
async def planifier_mise_a_jour(
    module_id: uuid.UUID,
    corps: UpgradePlanRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> UpgradePlanResponse:
    """Renvoie le plan (étapes, `rollbackPossible`, `forwardOnly`) et le journalise.

    Droit `platform.module.publish` (même portée plateforme que l'évaluation). Le plan n'est jamais
    exécuté ici : l'application d'une version relève d'une tâche distincte."""
    exiger_droit_plateforme(utilisateur.id, PLATFORM_MODULE_PUBLISH)
    ligne = await compatibilite_service.planifier_mise_a_jour(
        db, module_id, from_version=corps.fromVersion, to_version=corps.toVersion
    )
    await db.commit()
    return UpgradePlanResponse.model_validate(ligne)
