"""Stations : fiche station, services, politique de prix, produits carburant par station.

Responsabilité : CRUD des stations et de leur référentiel (produits carburant de station,
services, politique tarifaire) et lectures scopées par organisation.
N'y appartiennent pas : cuves, pompes, capteurs (`tanks/`) ; prix historiques, résolution de
prix, caisse et déclarations (`service.py`). Ce module n'importe jamais `service.py` (cycle).
`service.py` réexporte ces fonctions : les anciens chemins restent valides.
"""

import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.modules.zylo_liquid.permissions import (
    STATION_READ,
    STATION_SERVICE_MANAGE,
    STATION_SERVICE_READ,
    PRICING_POLICY_MANAGE,
    PRICING_POLICY_READ,
)
from app.rbac.service import list_visible_resource_ids
from app.modules.zylo_liquid.models import (
    FuelProduct,
    Station,
    StationFuelProduct,
    StationProductPricingPolicy,
    StationService,
    Tank,
)
from app.modules.zylo_liquid.stations.schemas import (
    CreateFuelProductRequest,
    CreateStationFuelProductRequest,
    CreateStationRequest,
    CreateStationServiceRequest,
    UpdateStationServiceRequest,
    StationServiceResponse,
    UpdatePricingPolicyRequest,
    PricingPolicyResponse,
    StationFuelProductResponse,
    StationResponse,
    UpdateStationFuelProductRequest,
    UpdateStationRequest,
)
from app.shared.currency import Currency
from app.shared.geo import City
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta
from app.modules.zylo_liquid.common import _check_declaration_scope, fuel_product_list_cache


async def create_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, data: CreateFuelProductRequest
) -> FuelProduct:
    existing = await db.execute(
        select(FuelProduct).where(
            FuelProduct.organizationId == organization_id, FuelProduct.code == data.code
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="fuel_product_code_already_used",
            message=f"Un produit carburant avec le code '{data.code}' existe déjà pour cette organisation.",
            status_code=409,
        )

    fuel_product = FuelProduct(organizationId=organization_id, **data.model_dump())
    db.add(fuel_product)
    await db.commit()
    await db.refresh(fuel_product)
    fuel_product_list_cache.invalidate_prefix(f"org:{organization_id}:")
    return fuel_product


async def get_fuel_product(db: AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID) -> FuelProduct:
    result = await db.execute(
        select(FuelProduct).where(
            FuelProduct.id == fuel_product_id, FuelProduct.organizationId == organization_id
        )
    )
    fuel_product = result.scalar_one_or_none()
    if fuel_product is None:
        raise AppError(code="fuel_product_not_found", message="Produit carburant introuvable.", status_code=404)
    return fuel_product


async def create_station_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, data: CreateStationFuelProductRequest
) -> StationFuelProduct:
    """Associe explicitement un produit à une station — jamais déduite d'une
    cuve ou d'un prix existant (page_configuration.md §15). Vérifie que la
    station et le produit appartiennent bien à l'organisation courante."""
    station = await db.execute(
        select(Station.id).where(Station.id == data.stationId, Station.organizationId == organization_id)
    )
    if station.scalar_one_or_none() is None:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)

    fuel_product = await db.execute(
        select(FuelProduct.id).where(FuelProduct.id == data.fuelProductId, FuelProduct.organizationId == organization_id)
    )
    if fuel_product.scalar_one_or_none() is None:
        raise AppError(code="fuel_product_not_found", message="Produit carburant introuvable.", status_code=404)

    existing = await db.execute(
        select(StationFuelProduct).where(
            StationFuelProduct.stationId == data.stationId, StationFuelProduct.fuelProductId == data.fuelProductId
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        if not row.active:
            row.active = True
            await db.commit()
            await db.refresh(row)
        return row

    association = StationFuelProduct(stationId=data.stationId, fuelProductId=data.fuelProductId)
    db.add(association)
    await db.commit()
    await db.refresh(association)
    return association


async def list_station_fuel_products(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    fuel_product_id: uuid.UUID | None,
) -> Page:
    stmt = (
        select(StationFuelProduct)
        .join(Station, Station.id == StationFuelProduct.stationId)
        .where(Station.organizationId == organization_id)
    )
    if station_id is not None:
        stmt = stmt.where(StationFuelProduct.stationId == station_id)
    if fuel_product_id is not None:
        stmt = stmt.where(StationFuelProduct.fuelProductId == fuel_product_id)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    data = [StationFuelProductResponse.model_validate(row) for row in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def update_station_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, association_id: uuid.UUID, data: UpdateStationFuelProductRequest
) -> StationFuelProduct:
    result = await db.execute(
        select(StationFuelProduct)
        .join(Station, Station.id == StationFuelProduct.stationId)
        .where(StationFuelProduct.id == association_id, Station.organizationId == organization_id)
    )
    association = result.scalar_one_or_none()
    if association is None:
        raise AppError(code="station_fuel_product_not_found", message="Association station/produit introuvable.", status_code=404)
    association.active = data.active
    await db.commit()
    await db.refresh(association)
    return association


async def create_station_service(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateStationServiceRequest) -> StationServiceResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_SERVICE_MANAGE)
    instance = StationService(stationId=data.stationId, type=data.type, label=data.label, available=data.available)
    db.add(instance)
    await db.flush()
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationService.create", entity_type="StationService", entity_id=instance.id,
        summary=f"Ajout du service {data.label}", scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(instance)
    return StationServiceResponse.model_validate(instance)


async def update_station_service(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, service_id: uuid.UUID, data: UpdateStationServiceRequest) -> StationServiceResponse:
    result = await db.execute(
        select(StationService, Station)
        .join(Station, Station.id == StationService.stationId)
        .where(StationService.id == service_id, Station.organizationId == organization_id)
    )
    row = result.one_or_none()
    if row is None:
        raise AppError(code="station_service_not_found", message="Service introuvable.", status_code=404)
    instance, station = row
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_SERVICE_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(instance, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationService.update", entity_type="StationService", entity_id=instance.id,
        summary=f"Modification du service {instance.label}", scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(instance)
    return StationServiceResponse.model_validate(instance)


async def list_station_services(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> list[StationServiceResponse]:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_SERVICE_READ)
    result = await db.execute(select(StationService).where(StationService.stationId == station_id).order_by(StationService.label))
    return [StationServiceResponse.model_validate(r) for r in result.scalars().all()]


async def get_pricing_policy(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, fuel_product_id: uuid.UUID) -> PricingPolicyResponse | None:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PRICING_POLICY_READ)
    result = await db.execute(
        select(StationProductPricingPolicy).where(
            StationProductPricingPolicy.stationId == station_id, StationProductPricingPolicy.fuelProductId == fuel_product_id
        )
    )
    instance = result.scalar_one_or_none()
    return PricingPolicyResponse.model_validate(instance) if instance is not None else None


async def update_pricing_policy(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, fuel_product_id: uuid.UUID, data: UpdatePricingPolicyRequest) -> PricingPolicyResponse:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PRICING_POLICY_MANAGE)
    await get_fuel_product(db, organization_id, fuel_product_id)
    result = await db.execute(
        select(StationProductPricingPolicy).where(
            StationProductPricingPolicy.stationId == station_id, StationProductPricingPolicy.fuelProductId == fuel_product_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        instance = StationProductPricingPolicy(stationId=station_id, fuelProductId=fuel_product_id)
        db.add(instance)
        await db.flush()
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(instance, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.pricingPolicy.update", entity_type="StationProductPricingPolicy", entity_id=instance.id,
        summary="Modification de la politique commerciale", scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(instance)
    return PricingPolicyResponse.model_validate(instance)


async def _assert_city_exists(db: AsyncSession, city_id: uuid.UUID) -> None:
    result = await db.execute(select(City.id).where(City.id == city_id))
    if result.scalar_one_or_none() is None:
        raise AppError(code="city_not_found", message="Ville inconnue du référentiel géographique.", status_code=422)


async def _assert_currency_exists(db: AsyncSession, currency_id: uuid.UUID) -> None:
    result = await db.execute(select(Currency.id).where(Currency.id == currency_id))
    if result.scalar_one_or_none() is None:
        raise AppError(code="currency_not_found", message="Devise inconnue du référentiel.", status_code=422)


async def create_station(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateStationRequest
) -> Station:
    if data.cityId is not None:
        await _assert_city_exists(db, data.cityId)
    if data.currencyOverrideId is not None:
        await _assert_currency_exists(db, data.currencyOverrideId)

    existing = await db.execute(
        select(Station).where(Station.organizationId == organization_id, Station.code == data.code)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="station_code_already_used",
            message=f"Une station avec le code '{data.code}' existe déjà pour cette organisation.",
            status_code=409,
        )

    station = Station(organizationId=organization_id, status="active", **data.model_dump())
    db.add(station)
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.station.create",
        entity_type="Station",
        entity_id=station.id,
        summary=f"Création de la station {station.name}",
        scope_resource_type="station",
        scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(station)
    return station


async def get_station(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    result = await db.execute(
        select(Station).where(Station.id == station_id, Station.organizationId == organization_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    return station


async def update_station(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, data: UpdateStationRequest
) -> Station:
    station = await get_station(db, organization_id, station_id)
    updates = data.model_dump(exclude_unset=True)
    if "cityId" in updates and updates["cityId"] is not None:
        await _assert_city_exists(db, updates["cityId"])
    if "currencyOverrideId" in updates and updates["currencyOverrideId"] is not None:
        await _assert_currency_exists(db, updates["currencyOverrideId"])
    before = {field: getattr(station, field) for field in updates}
    for field, value in updates.items():
        setattr(station, field, value)
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.station.update",
        entity_type="Station",
        entity_id=station.id,
        summary=f"Modification de la station {station.name}",
        changes={field: {"before": str(before[field]), "after": str(updates[field])} for field in updates},
        scope_resource_type="station",
        scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(station)
    return station


async def deactivate_station(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    station = await get_station(db, organization_id, station_id)
    if station.status == "inactive":
        raise AppError(code="station_already_inactive", message="Cette station est déjà désactivée.", status_code=409)
    station.status = "inactive"
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.station.close",
        entity_type="Station",
        entity_id=station.id,
        summary=f"Fermeture de la station {station.name}",
        scope_resource_type="station",
        scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(station)
    return station


async def reactivate_station(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    station = await get_station(db, organization_id, station_id)
    if station.status == "active":
        raise AppError(code="station_already_active", message="Cette station est déjà active.", status_code=409)
    station.status = "active"
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.station.reopen",
        entity_type="Station",
        entity_id=station.id,
        summary=f"Réouverture de la station {station.name}",
        scope_resource_type="station",
        scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(station)
    return station


async def list_stations(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    city_id: uuid.UUID | None,
    status: str | None,
) -> Page:
    """Filtrée selon la portée réelle de l'utilisateur — un gérant dont le
    rôle n'est attribué que sur SA station (`UserRole.resourceType="station"`)
    ne voit que celle-ci ici, jamais le réseau entier (résout le point
    bloquant de `processus-double-sources-verite/02-modele-double-source.md`
    §6 : la portée existait déjà côté vérification, elle est maintenant
    appliquée au filtrage des listes)."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, STATION_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {STATION_READ}.", status_code=403)

    stmt = select(Station).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(Station.id.in_(visible_station_ids))
    if city_id is not None:
        stmt = stmt.where(Station.cityId == city_id)
    if status is not None:
        stmt = stmt.where(Station.status == status)
    stmt = stmt.order_by(Station.name)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    stations = result.scalars().all()

    station_ids = [station.id for station in stations]
    tank_counts: dict[uuid.UUID, int] = {}
    if station_ids:
        count_result = await db.execute(
            select(Tank.stationId, func.count()).where(Tank.stationId.in_(station_ids), Tank.active.is_(True)).group_by(Tank.stationId)
        )
        tank_counts = dict(count_result.all())

    data = [
        StationResponse.model_validate(station).model_copy(update={"activeTankCount": tank_counts.get(station.id, 0)})
        for station in stations
    ]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))
