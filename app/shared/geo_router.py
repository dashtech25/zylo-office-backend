"""Lecture seule du référentiel géographique Core (pays/régions/villes) —
déjà en base (voir app/shared/geo.py) mais jamais exposé par aucun
endpoint jusqu'ici. Ajouté pour le sélecteur de ville de Zylo Liquid
(création de station, filtre de la liste des stations) : donnée réelle,
CAS 2 de la mission d'intégration (existe en base, pas encore exposée)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.rbac.service import require_permission
from app.shared.geo import City, Country, Region
from app.shared.geo_schemas import CityResponse, CountryResponse
from app.shared.pagination import PaginationParams
from app.shared.permissions import GEO_READ
from app.shared.schemas import Page, PageMeta
from app.shared.simple_cache import TTLCache

geo_router = APIRouter()

# Cache TTL 60s : référentiel géographique global (pas de organizationId sur
# City/Region/Country), quasi statique (Phase 1 audit, pb #3). Aucun
# endpoint d'écriture n'existe pour City/Region/Country dans l'app
# (vérifié par grep) : pas d'invalidation à câbler, le TTL suffit à borner
# toute dérive si la donnée change un jour par un autre canal (migration,
# accès direct DB).
_city_list_cache = TTLCache(default_ttl_seconds=60.0)
_country_list_cache = TTLCache(default_ttl_seconds=60.0)


@geo_router.get("", response_model=Page[CityResponse], dependencies=[Depends(require_permission(GEO_READ))])
async def list_cities(
    q: str | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Page:
    cache_key = f"q:{q or ''}:limit:{pagination.limit}:offset:{pagination.offset}"
    cached = _city_list_cache.get(cache_key)
    if cached is not None:
        return cached
    # Requête à colonnes multiples (jointure ville/région/pays) : le helper
    # générique `paginate()` appelle `.scalars()`, qui ne garderait que la
    # première colonne de chaque ligne — inadapté ici, pagination réécrite
    # explicitement avec `.all()` pour conserver les colonnes jointes.
    stmt = (
        select(
            City.id,
            City.name,
            Region.id.label("regionId"),
            Region.name.label("regionName"),
            Country.id.label("countryId"),
            Country.name.label("countryName"),
            Country.currencyId,
            Country.currencyCode,
        )
        .join(Region, Region.id == City.regionId)
        .join(Country, Country.id == Region.countryId)
        .where(City.active.is_(True))
        .order_by(City.name)
    )
    if q:
        stmt = stmt.where(City.name.ilike(f"%{q}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    page = Page(
        data=[CityResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )
    _city_list_cache.set(cache_key, page)
    return page


# Routeur séparé (préfixe "/countries" côté api/v1/router.py, à ne pas
# confondre avec `geo_router` ci-dessus, préfixé "/cities") — même
# référentiel Core, exposé pour le sélecteur de pays du formulaire de
# création de station (P1-1, audit module Stations 2026-09-16: le champ
# Pays manquait alors que la Ville en dépend directement).
country_router = APIRouter()


@country_router.get("", response_model=Page[CountryResponse], dependencies=[Depends(require_permission(GEO_READ))])
async def list_countries(
    q: str | None = None,
    # Référentiel Core mondial (~250 pays, jamais paginé par région
    # organisationnelle) : plafond dédié plus haut que `PaginationParams`
    # (limité à 100, pensé pour des listes métier) pour que le sélecteur de
    # pays du formulaire de station puisse charger la liste complète en un
    # seul appel plutôt que de repagineter côté frontend.
    limit: int = Query(300, ge=1, le=300),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page:
    cache_key = f"q:{q or ''}:limit:{limit}:offset:{offset}"
    cached = _country_list_cache.get(cache_key)
    if cached is not None:
        return cached
    stmt = select(Country).where(Country.active.is_(True)).order_by(Country.name)
    if q:
        stmt = stmt.where(Country.name.ilike(f"%{q}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(limit).offset(offset))
    countries = result.scalars().all()
    page = Page(
        data=[CountryResponse.model_validate(c) for c in countries],
        meta=PageMeta(total=total or 0, limit=limit, offset=offset),
    )
    _country_list_cache.set(cache_key, page)
    return page
