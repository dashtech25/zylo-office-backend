"""Consultation publique du catalogue de modules (BE-043), montée sous `/api/v1/catalog`.

Deux lectures, sans authentification ni tenant :

- `lister_modules_catalogue` : seuls les modules `publicationState = published` ET
  `visibility = visible` sont listés (CA-1). Les autres ne sont jamais renvoyés, même par pagination.
- `lire_fiche_catalogue` : la fiche d'un module, selon l'ordre suivant :
  1. module absent, `hidden`, ou non `published` -> 404 `MODULE_NOT_FOUND` avec un corps unique,
     identique pour « inexistant » et « masqué » (pas de révélation d'existence, CA-2) ;
  2. module `published` mais `restricted` -> 403 `MODULE_AUDIENCE_RESTRICTED` : le refus est
     explicite, car la règle d'audience n'est pas définie (QE-MOD-12) et on refuse par défaut ;
  3. sinon la fiche, avec les seules versions `published` (CA-4 : jamais `draft` ni `review`).

Visibilité et état de publication sont deux axes orthogonaux (matrice-etats, section 1) : la
publication seule n'ouvre pas la fiche, la visibilité seule non plus. Les fonctions ne font aucune
écriture.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.models import Module, ModuleVersion
from app.modules_registry.schemas import CatalogueModuleResponse, FicheModuleCatalogue
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page


def _critere_listable():
    """Clause SQL commune : publié ET visible. Source unique de la règle de liste."""
    return (Module.publicationState == "published") & (Module.visibility == "visible")


async def lister_modules_catalogue(db: AsyncSession, pagination: PaginationParams) -> Page:
    """Liste paginée des modules publiés et visibles, triés par `code` (slug)."""
    stmt = select(Module).where(_critere_listable()).order_by(Module.code)
    return await paginate(db, stmt, pagination, CatalogueModuleResponse)


async def lire_fiche_catalogue(db: AsyncSession, slug: str) -> FicheModuleCatalogue:
    """Fiche publique d'un module identifié par son `slug` (`module.code`).

    Lève `MODULE_NOT_FOUND` (404) pour un module absent, masqué ou non publié, et
    `MODULE_AUDIENCE_RESTRICTED` (403) pour un module publié mais restreint. Voir la docstring du
    module pour l'ordre des contrôles.
    """
    module = (await db.execute(select(Module).where(Module.code == slug))).scalar_one_or_none()
    if module is None or module.publicationState != "published" or module.visibility == "hidden":
        raise AppError(code="MODULE_NOT_FOUND", message="Module introuvable.", status_code=404)
    if module.visibility == "restricted":
        raise AppError(
            code="MODULE_AUDIENCE_RESTRICTED",
            message="Module réservé à une audience qui ne vous est pas ouverte.",
            status_code=403,
        )
    if module.visibility != "visible":
        raise AppError(code="MODULE_NOT_FOUND", message="Module introuvable.", status_code=404)

    versions = (
        await db.execute(
            select(ModuleVersion)
            .where(ModuleVersion.moduleId == module.id, ModuleVersion.publicationState == "published")
            .order_by(ModuleVersion.publishedAt, ModuleVersion.version)
        )
    ).scalars().all()
    return FicheModuleCatalogue(
        code=module.code,
        name=module.name,
        description=module.description,
        versions=[{"version": v.version, "publishedAt": v.publishedAt} for v in versions],
    )
