"""Lecture du catalogue par code de module et par version (BE-194).

Deux routes, montées sous `/api/v1/modules` :

- `GET /{module_code}` : fiche du module, avec les seules versions proposées à l'installation ;
- `GET /{module_code}/versions/{version}` : une version du module.

Lecture publique, sans authentification ni droit : la lecture du catalogue n'accorde aucun droit,
et aucun droit n'est inféré du listing (CA-2). La visibilité est celle du catalogue public
(`catalog_lecture.charger_module_visible`, BE-043) : module absent, masqué ou non publié -> 404
`MODULE_NOT_FOUND` ; restreint -> 403 `MODULE_AUDIENCE_RESTRICTED`.

Règles de version :
- une version inconnue, ou non publiée (`draft`, `review`) -> 404 `MODULE_VERSION_NOT_FOUND` ;
- une version `deprecated` -> 422 `MODULE_VERSION_DEPRECATED` (erreur explicite, CA-1) ;
- une version installable est `published` et a une `compatibility` renseignée (CA-4). La
  compatibilité déclarée est la seule condition retenue ici ; l'évaluation complète contre le
  catalogue reste dans `compatibilite_service` (BE-044).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.modules_registry.catalog_lecture import charger_module_visible
from app.modules_registry.models import ModuleVersion
from app.modules_registry.schemas import FicheModuleInstallable, VersionModuleCatalogue

router = APIRouter()


@router.get(
    "/{module_code}",
    response_model=FicheModuleInstallable,
    summary="Fiche d'un module du catalogue, avec ses versions installables",
)
async def lire_module(module_code: str, db: AsyncSession = Depends(get_db)) -> FicheModuleInstallable:
    """Fiche d'un module visible. `versions` ne contient que les versions `published` et compatibles."""
    module = await charger_module_visible(db, module_code)
    versions = (
        await db.execute(
            select(ModuleVersion)
            .where(ModuleVersion.moduleId == module.id, ModuleVersion.publicationState == "published")
            .order_by(ModuleVersion.publishedAt, ModuleVersion.version)
        )
    ).scalars().all()
    # `compatibility` est un JSON : un None Python est persisté en JSON `null`, pas en SQL NULL,
    # donc le filtre se fait ici et non en SQL.
    installables = [v for v in versions if v.compatibility is not None]
    return FicheModuleInstallable(
        code=module.code,
        name=module.name,
        description=module.description,
        versions=[VersionModuleCatalogue.model_validate(v) for v in installables],
    )


@router.get(
    "/{module_code}/versions/{version}",
    response_model=VersionModuleCatalogue,
    summary="Une version d'un module du catalogue",
)
async def lire_version(module_code: str, version: str, db: AsyncSession = Depends(get_db)) -> VersionModuleCatalogue:
    """Version d'un module visible. Erreurs : 404 inconnue ou non publiée, 422 dépréciée (voir module)."""
    module = await charger_module_visible(db, module_code)
    ligne = (
        await db.execute(
            select(ModuleVersion).where(ModuleVersion.moduleId == module.id, ModuleVersion.version == version)
        )
    ).scalar_one_or_none()
    if ligne is None or ligne.publicationState in ("draft", "review"):
        raise AppError(code="MODULE_VERSION_NOT_FOUND", message="Version introuvable.", status_code=404)
    if ligne.publicationState == "deprecated":
        raise AppError(
            code="MODULE_VERSION_DEPRECATED",
            message="Version dépréciée : elle n'est plus proposée à l'installation.",
            status_code=422,
        )
    return VersionModuleCatalogue.model_validate(ligne)
