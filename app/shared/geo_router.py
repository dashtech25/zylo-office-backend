"""Lecture seule du référentiel géographique Core (pays/régions/villes) —
déjà en base (voir app/shared/geo.py) mais jamais exposé par aucun
endpoint jusqu'ici. Ajouté pour le sélecteur de ville de Zylo Liquid
(création de station, filtre de la liste des stations) : donnée réelle,
CAS 2 de la mission d'intégration (existe en base, pas encore exposée)."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.rbac.service import require_permission
from app.shared.geo import City, Country, Region
from app.shared.geo_schemas import CityResponse
from app.shared.pagination import PaginationParams
from app.shared.permissions import GEO_READ
from app.shared.schemas import Page, PageMeta

geo_router = APIRouter()


@geo_router.get("", response_model=Page[CityResponse], dependencies=[Depends(require_permission(GEO_READ))])
async def list_cities(
    q: str | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Page:
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
    return Page(
        data=[CityResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )
