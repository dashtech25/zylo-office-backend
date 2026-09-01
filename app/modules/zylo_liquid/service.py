import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_liquid.models import (
    FuelProduct,
    HolykellAccount,
    HolykellDeviceRegistry,
    Station,
    Tank,
    TankCalibrationPoint,
    TankSensorMapping,
)
from app.modules.zylo_liquid.schemas import (
    CreateFuelProductRequest,
    CreateStationRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    ReplaceTankCalibrationPointsRequest,
    StationResponse,
    TankResponse,
    TankSensorMappingResponse,
    UpdateFuelProductRequest,
    UpdateStationRequest,
    UpdateTankRequest,
)
from app.shared.geo import City
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta


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


async def update_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID, data: UpdateFuelProductRequest
) -> FuelProduct:
    fuel_product = await get_fuel_product(db, organization_id, fuel_product_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fuel_product, field, value)
    await db.commit()
    await db.refresh(fuel_product)
    return fuel_product


async def _assert_city_exists(db: AsyncSession, city_id: uuid.UUID) -> None:
    result = await db.execute(select(City.id).where(City.id == city_id))
    if result.scalar_one_or_none() is None:
        raise AppError(code="city_not_found", message="Ville inconnue du référentiel géographique.", status_code=422)


async def create_station(db: AsyncSession, organization_id: uuid.UUID, data: CreateStationRequest) -> Station:
    if data.cityId is not None:
        await _assert_city_exists(db, data.cityId)

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
    db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID, data: UpdateStationRequest
) -> Station:
    station = await get_station(db, organization_id, station_id)
    updates = data.model_dump(exclude_unset=True)
    if "cityId" in updates and updates["cityId"] is not None:
        await _assert_city_exists(db, updates["cityId"])
    for field, value in updates.items():
        setattr(station, field, value)
    await db.commit()
    await db.refresh(station)
    return station


async def deactivate_station(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    station = await get_station(db, organization_id, station_id)
    if station.status == "inactive":
        raise AppError(code="station_already_inactive", message="Cette station est déjà désactivée.", status_code=409)
    station.status = "inactive"
    await db.commit()
    await db.refresh(station)
    return station


async def reactivate_station(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    station = await get_station(db, organization_id, station_id)
    if station.status == "active":
        raise AppError(code="station_already_active", message="Cette station est déjà active.", status_code=409)
    station.status = "active"
    await db.commit()
    await db.refresh(station)
    return station


async def list_stations(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    city_id: uuid.UUID | None,
    status: str | None,
) -> Page:
    stmt = select(Station).where(Station.organizationId == organization_id)
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


async def create_tank(db: AsyncSession, organization_id: uuid.UUID, data: CreateTankRequest) -> Tank:
    await get_station(db, organization_id, data.stationId)  # lève station_not_found si hors périmètre

    has_existing_product = data.fuelProductId is not None
    has_new_product = data.newFuelProductName is not None or data.newFuelProductCode is not None
    if has_existing_product == has_new_product:
        raise AppError(
            code="fuel_product_selection_invalid",
            message="Fournir soit fuelProductId, soit newFuelProductName + newFuelProductCode — jamais les deux, ni aucun des deux.",
            status_code=422,
        )

    existing = await db.execute(
        select(Tank).where(Tank.stationId == data.stationId, Tank.tankNumber == data.tankNumber)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="tank_number_already_used",
            message=f"Le numéro de cuve {data.tankNumber} est déjà utilisé dans cette station.",
            status_code=409,
        )

    if has_existing_product:
        fuel_product = await get_fuel_product(db, organization_id, data.fuelProductId)
    else:
        if not data.newFuelProductName or not data.newFuelProductCode:
            raise AppError(
                code="fuel_product_selection_invalid",
                message="newFuelProductName et newFuelProductCode sont tous deux requis pour créer un produit à la volée.",
                status_code=422,
            )
        fuel_product = await create_fuel_product(
            db, organization_id, CreateFuelProductRequest(name=data.newFuelProductName, code=data.newFuelProductCode)
        )

    tank_fields = data.model_dump(exclude={"fuelProductId", "newFuelProductName", "newFuelProductCode"})
    tank = Tank(fuelProductId=fuel_product.id, **tank_fields)
    db.add(tank)
    await db.commit()
    await db.refresh(tank)
    return tank


async def _assert_tank_station_in_organization(db: AsyncSession, organization_id: uuid.UUID, tank: Tank) -> None:
    result = await db.execute(
        select(Station.id).where(Station.id == tank.stationId, Station.organizationId == organization_id)
    )
    if result.scalar_one_or_none() is None:
        raise AppError(code="tank_not_found", message="Cuve introuvable.", status_code=404)


async def get_tank(db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> Tank:
    result = await db.execute(select(Tank).where(Tank.id == tank_id))
    tank = result.scalar_one_or_none()
    if tank is None:
        raise AppError(code="tank_not_found", message="Cuve introuvable.", status_code=404)
    await _assert_tank_station_in_organization(db, organization_id, tank)
    return tank


async def update_tank(
    db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID, data: UpdateTankRequest
) -> Tank:
    tank = await get_tank(db, organization_id, tank_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tank, field, value)
    await db.commit()
    await db.refresh(tank)
    return tank


async def list_tanks(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    fuel_product_id: uuid.UUID | None,
    active: bool | None,
) -> Page:
    stmt = select(Tank).join(Station, Station.id == Tank.stationId).where(Station.organizationId == organization_id)
    if station_id is not None:
        stmt = stmt.where(Tank.stationId == station_id)
    if fuel_product_id is not None:
        stmt = stmt.where(Tank.fuelProductId == fuel_product_id)
    if active is not None:
        stmt = stmt.where(Tank.active.is_(active))
    stmt = stmt.order_by(Tank.tankNumber)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    tanks = result.scalars().all()
    data = [TankResponse.model_validate(tank) for tank in tanks]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def create_tank_sensor_mapping(
    db: AsyncSession, organization_id: uuid.UUID, data: CreateTankSensorMappingRequest
) -> TankSensorMapping:
    tank = await get_tank(db, organization_id, data.tankId)

    # hkSerialNumber (numéro de série physique) correspond à plusieurs lignes
    # du registre Holykell — une par canal de mesure. Résolu via hkSensorName
    # préfixé par measurementType, confirmé sur la base réelle zylo_liquid
    # (ex. "product_level Cuve 1", "water_level Cuve 1", "temperature Cuve 1"
    # — issue #29), jamais une invention.
    result = await db.execute(
        select(HolykellDeviceRegistry).where(
            HolykellDeviceRegistry.hkSerialNumber == data.hkSerialNumber,
            HolykellDeviceRegistry.hkSensorName.ilike(f"{data.measurementType}%"),
        )
    )
    registry_entry = result.scalars().first()
    if registry_entry is None:
        raise AppError(
            code="sensor_not_found_in_holykell_registry",
            message="Ce capteur n'a pas encore été vu par Holykell, vérifier qu'il est bien configuré côté plateforme du fabricant.",
            status_code=422,
        )

    existing = await db.execute(
        select(TankSensorMapping).where(
            TankSensorMapping.tankId == tank.id,
            TankSensorMapping.measurementType == data.measurementType,
            TankSensorMapping.active.is_(True),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="tank_sensor_mapping_already_active",
            message="Une association active existe déjà pour cette cuve et ce type de mesure — la clore d'abord.",
            status_code=409,
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # colonnes TIMESTAMP WITHOUT TIME ZONE (Phase 1)
    mapping = TankSensorMapping(
        hkSensorId=registry_entry.hkSensorId,
        tankId=tank.id,
        measurementType=data.measurementType,
        validFrom=now,
        active=True,
        createdAt=now,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    return mapping


async def get_tank_sensor_mapping(db: AsyncSession, organization_id: uuid.UUID, mapping_id: uuid.UUID) -> TankSensorMapping:
    result = await db.execute(select(TankSensorMapping).where(TankSensorMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise AppError(code="tank_sensor_mapping_not_found", message="Association introuvable.", status_code=404)
    await get_tank(db, organization_id, mapping.tankId)  # lève tank_not_found si hors périmètre
    return mapping


async def close_tank_sensor_mapping(db: AsyncSession, organization_id: uuid.UUID, mapping_id: uuid.UUID) -> TankSensorMapping:
    mapping = await get_tank_sensor_mapping(db, organization_id, mapping_id)
    if not mapping.active:
        raise AppError(code="tank_sensor_mapping_already_closed", message="Cette association est déjà close.", status_code=409)
    mapping.active = False
    mapping.validUntil = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(mapping)
    return mapping


async def list_tank_sensor_mappings(
    db: AsyncSession, organization_id: uuid.UUID, pagination: PaginationParams, tank_id: uuid.UUID | None
) -> Page:
    stmt = (
        select(TankSensorMapping)
        .join(Tank, Tank.id == TankSensorMapping.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if tank_id is not None:
        stmt = stmt.where(TankSensorMapping.tankId == tank_id)
    stmt = stmt.order_by(TankSensorMapping.validFrom.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    mappings = result.scalars().all()
    data = [TankSensorMappingResponse.model_validate(mapping) for mapping in mappings]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def replace_tank_calibration_points(
    db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID, data: ReplaceTankCalibrationPointsRequest
) -> list[TankCalibrationPoint]:
    tank = await get_tank(db, organization_id, tank_id)

    sorted_points = sorted(data.points, key=lambda p: p.heightMm)
    max_height = sorted_points[-1].heightMm
    if tank.tankHeightMm is not None and max_height > tank.tankHeightMm:
        raise AppError(
            code="calibration_height_exceeds_tank",
            message=f"La hauteur maximale de la table ({max_height} mm) dépasse la hauteur physique déclarée de la cuve ({tank.tankHeightMm} mm).",
            status_code=422,
        )

    for previous, current in zip(sorted_points, sorted_points[1:]):
        if current.volumeLiters < previous.volumeLiters:
            raise AppError(
                code="calibration_table_not_monotonic",
                message="Le volume ne doit jamais diminuer alors que la hauteur augmente — table de calibration incohérente.",
                status_code=422,
            )

    # Remplacement intégral, jamais une fusion partielle (Point 2 §1.4).
    await db.execute(TankCalibrationPoint.__table__.delete().where(TankCalibrationPoint.tankId == tank_id))
    new_points = [
        TankCalibrationPoint(tankId=tank_id, heightMm=point.heightMm, volumeLiters=point.volumeLiters)
        for point in sorted_points
    ]
    db.add_all(new_points)
    await db.commit()
    for point in new_points:
        await db.refresh(point)
    return new_points


async def list_tank_calibration_points(db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> list[TankCalibrationPoint]:
    await get_tank(db, organization_id, tank_id)  # lève tank_not_found si hors périmètre
    result = await db.execute(
        select(TankCalibrationPoint).where(TankCalibrationPoint.tankId == tank_id).order_by(TankCalibrationPoint.heightMm)
    )
    return list(result.scalars().all())


async def get_holykell_account_sync_status(db: AsyncSession, organization_id: uuid.UUID, account_id: uuid.UUID) -> HolykellAccount:
    result = await db.execute(
        select(HolykellAccount).where(HolykellAccount.id == account_id, HolykellAccount.organizationId == organization_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AppError(code="holykell_account_not_found", message="Compte Holykell introuvable.", status_code=404)
    return account
