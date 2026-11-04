"""Routes publiques du catalogue de modules (BE-043), montées sous `/api/v1/catalog`.

- `GET /modules` : liste paginée des modules publiés et visibles (200) ;
- `GET /modules/{slug}` : fiche d'un module (200), 404 si masqué ou inconnu, 403 si restreint.

Aucune authentification ni tenant : la visibilité est la seule barrière, décidée par
`catalog_lecture`. Ces routes ne doivent jamais exposer de version `draft` ou `review`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules_registry import catalog_lecture
from app.modules_registry.schemas import FicheModuleCatalogue
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page

router = APIRouter(prefix="/modules", tags=["catalog"])


@router.get("", response_model=Page, summary="Catalogue public : modules publiés et visibles")
async def lister_modules(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)) -> Page:
    """Liste paginée, sans authentification. Un module masqué, restreint ou non publié n'apparaît pas."""
    return await catalog_lecture.lister_modules_catalogue(db, pagination)


@router.get(
    "/{slug}",
    response_model=FicheModuleCatalogue,
    summary="Catalogue public : fiche d'un module visible",
)
async def lire_fiche(slug: str, db: AsyncSession = Depends(get_db)) -> FicheModuleCatalogue:
    """Fiche d'un module publié et visible, avec ses seules versions publiées.

    404 `MODULE_NOT_FOUND` pour un module masqué ou inconnu (même réponse), 403
    `MODULE_AUDIENCE_RESTRICTED` pour un module restreint.
    """
    return await catalog_lecture.lire_fiche_catalogue(db, slug)
