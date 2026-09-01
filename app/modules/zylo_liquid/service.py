import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_liquid.algorithms import (
    correct_volume_to_reference_temperature,
    detect_deliveries,
    interpolate_height_to_volume,
)
from app.modules.zylo_liquid.models import (
    DeliveryDetected,
    FuelProduct,
    HolykellAccount,
    HolykellDeviceRegistry,
    Station,
    Tank,
    TankCalibrationPoint,
    TankMeasurement,
    TankSensorMapping,
)
from app.modules.zylo_liquid.schemas import (
    CreateFuelProductRequest,
    CreateStationRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    DeliveryDetectedResponse,
    NetworkSummaryProductLine,
    NetworkSummaryResponse,
    ReplaceTankCalibrationPointsRequest,
    StationCurrentStateResponse,
    StationResponse,
    TankCurrentStateResponse,
    TankMeasurementResponse,
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


async def _get_active_registry_entry(db: AsyncSession, tank_id: uuid.UUID, measurement_type: str) -> HolykellDeviceRegistry | None:
    result = await db.execute(
        select(HolykellDeviceRegistry)
        .join(TankSensorMapping, TankSensorMapping.hkSensorId == HolykellDeviceRegistry.hkSensorId)
        .where(
            TankSensorMapping.tankId == tank_id,
            TankSensorMapping.measurementType == measurement_type,
            TankSensorMapping.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_tank_current_state(db: AsyncSession, tank: Tank) -> TankCurrentStateResponse:
    """Construit l'état actuel d'une cuve — mesure instantanée lue depuis
    HolykellDeviceRegistry.lastValue/lastValueAt/hkLastStatus (jamais
    TankMeasurement, réservé à l'historique), conforme à
    nouveau-zylo-liquid/Point 6 §6.4. Algorithmes appelés depuis
    app.modules.zylo_liquid.algorithms, jamais réimplémentés ici (Point 3
    §10)."""
    product_level = await _get_active_registry_entry(db, tank.id, "product_level")

    if product_level is None or product_level.lastValue is None:
        return TankCurrentStateResponse(
            tankId=tank.id,
            tankNumber=tank.tankNumber,
            displayName=tank.displayName,
            sensorStatus="not_configured",
            heightMm=None,
            volumeLiters=None,
            volumeNotCalculableReason="no_active_sensor",
            volumeLiters15C=None,
            waterHeightMm=None,
            waterVolumeLiters=None,
            temperatureC=None,
            emptyVolumeLiters=None,
            lastMeasurementAt=None,
        )

    sensor_status = "online" if product_level.hkLastStatus == 1 else "offline"
    height_mm = float(product_level.lastValue)

    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank.id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]

    volume_brut = interpolate_height_to_volume(calibration_points, height_mm) if calibration_points else None
    volume_not_calculable_reason = None if volume_brut is not None else "no_calibration_table"

    water_registry = await _get_active_registry_entry(db, tank.id, "water_level")
    water_height_mm = float(water_registry.lastValue) if water_registry and water_registry.lastValue is not None else None
    water_volume = (
        interpolate_height_to_volume(calibration_points, water_height_mm)
        if water_height_mm is not None and calibration_points
        else (0.0 if water_height_mm is None else None)
    )

    volume_net = (volume_brut - water_volume) if (volume_brut is not None and water_volume is not None) else None
    empty_volume = (float(tank.capacityLiters) - volume_brut) if volume_brut is not None else None

    temperature_registry = await _get_active_registry_entry(db, tank.id, "temperature")
    temperature_c = (
        float(temperature_registry.lastValue) if temperature_registry and temperature_registry.lastValue is not None else None
    )

    volume_15c = None
    if volume_net is not None and temperature_c is not None:
        fuel_product = await db.get(FuelProduct, tank.fuelProductId)
        if fuel_product.thermalExpansionCoefficient is not None:
            volume_15c = correct_volume_to_reference_temperature(volume_net, temperature_c, float(fuel_product.thermalExpansionCoefficient))

    return TankCurrentStateResponse(
        tankId=tank.id,
        tankNumber=tank.tankNumber,
        displayName=tank.displayName,
        sensorStatus=sensor_status,
        heightMm=height_mm,
        volumeLiters=volume_net,
        volumeNotCalculableReason=volume_not_calculable_reason,
        volumeLiters15C=volume_15c,
        waterHeightMm=water_height_mm,
        waterVolumeLiters=water_volume,
        temperatureC=temperature_c,
        emptyVolumeLiters=empty_volume,
        lastMeasurementAt=product_level.lastValueAt,
    )


async def get_tank_current_state_by_id(db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> TankCurrentStateResponse:
    tank = await get_tank(db, organization_id, tank_id)
    return await get_tank_current_state(db, tank)


async def get_station_current_state(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> StationCurrentStateResponse:
    await get_station(db, organization_id, station_id)  # lève station_not_found si hors périmètre
    result = await db.execute(
        select(Tank).where(Tank.stationId == station_id, Tank.active.is_(True)).order_by(Tank.tankNumber)
    )
    tanks = result.scalars().all()
    states = [await get_tank_current_state(db, tank) for tank in tanks]
    return StationCurrentStateResponse(stationId=station_id, tanks=states)


async def list_tank_measurements(
    db: AsyncSession,
    organization_id: uuid.UUID,
    tank_id: uuid.UUID,
    pagination: PaginationParams,
    from_date,
    to_date,
) -> Page:
    """Historique des mesures d'une cuve (Point 2 §5.1) — inclut les
    mesures de tout capteur product_level ayant un jour été associé à cette
    cuve (mapping actif ou clos), pas seulement le capteur actuel : un
    remplacement de sonde ne doit jamais faire disparaître l'historique
    déjà collecté (issue #37)."""
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    tank = await get_tank(db, organization_id, tank_id)

    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == "product_level"
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]

    if not sensor_ids:
        return Page(data=[], meta=PageMeta(total=0, limit=pagination.limit, offset=pagination.offset))

    stmt = select(TankMeasurement).where(TankMeasurement.hkSensorId.in_(sensor_ids))
    if from_date is not None:
        stmt = stmt.where(TankMeasurement.measuredAt >= from_date)
    if to_date is not None:
        stmt = stmt.where(TankMeasurement.measuredAt <= to_date)
    stmt = stmt.order_by(TankMeasurement.measuredAt)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    measurements = result.scalars().all()

    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank.id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]

    data = [
        TankMeasurementResponse(
            id=m.id,
            measuredAt=m.measuredAt,
            rawValue=float(m.rawValue),
            unit=m.hkUnit,
            volumeLiters=interpolate_height_to_volume(calibration_points, float(m.rawValue)) if calibration_points else None,
            isCorrection=m.isCorrection,
        )
        for m in measurements
    ]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def get_network_summary(db: AsyncSession, organization_id: uuid.UUID, from_date, to_date) -> NetworkSummaryResponse:
    """Totaux réseau par produit (Point 2 §3.2) — agrège l'état actuel de
    chaque cuve (endpoint 7), jamais réimplémenté. Ne supporte que l'instant
    présent : Point 3 §11/§12 documente cet endpoint comme dépendant
    uniquement de l'état actuel, jamais de l'historique — une résolution
    rétroactive par période n'est pas spécifiée ici (voir issue #39,
    renvoyée au futur endpoint 13 « network/snapshot »)."""
    if from_date is not None or to_date is not None:
        raise AppError(
            code="historical_network_summary_not_supported",
            message="Le total réseau à une période passée n'est pas encore disponible à cet endpoint — utiliser network/snapshot (à venir) pour un instant précis dans le passé.",
            status_code=422,
        )

    stations_result = await db.execute(
        select(Station).where(Station.organizationId == organization_id, Station.status == "active")
    )
    stations = stations_result.scalars().all()
    station_ids = [s.id for s in stations]

    if not station_ids:
        return NetworkSummaryResponse(products=[], totalVolumeLiters=0, totalStationCount=0, totalTankCount=0)

    tanks_result = await db.execute(select(Tank).where(Tank.stationId.in_(station_ids), Tank.active.is_(True)))
    tanks = tanks_result.scalars().all()

    fuel_products_result = await db.execute(select(FuelProduct).where(FuelProduct.organizationId == organization_id))
    fuel_products_by_id = {fp.id: fp for fp in fuel_products_result.scalars().all()}

    per_product: dict[uuid.UUID, dict] = {}
    all_stations_with_data: set[uuid.UUID] = set()
    for tank in tanks:
        state = await get_tank_current_state(db, tank)
        if state.volumeLiters is None:
            continue  # cuve sans mesure calculable exclue du total (jamais un zéro, Point 2 §3.2)

        entry = per_product.setdefault(
            tank.fuelProductId,
            {"stations": set(), "tanks": 0, "volume": 0.0},
        )
        entry["stations"].add(tank.stationId)
        entry["tanks"] += 1
        entry["volume"] += state.volumeLiters
        all_stations_with_data.add(tank.stationId)

    products = [
        NetworkSummaryProductLine(
            fuelProductId=fuel_product_id,
            fuelProductName=fuel_products_by_id[fuel_product_id].name if fuel_product_id in fuel_products_by_id else "?",
            totalVolumeLiters=entry["volume"],
            stationCount=len(entry["stations"]),
            tankCount=entry["tanks"],
        )
        for fuel_product_id, entry in per_product.items()
    ]

    return NetworkSummaryResponse(
        products=products,
        totalVolumeLiters=sum(p.totalVolumeLiters for p in products),
        totalStationCount=len(all_stations_with_data),
        totalTankCount=sum(p.tankCount for p in products),
    )


async def run_delivery_detection_for_tank(db: AsyncSession, tank_id: uuid.UUID) -> list[DeliveryDetected]:
    """Exécute l'algorithme de détection de livraison (Point 8 §8.3,
    `detect_deliveries`, jamais réimplémenté) sur tout l'historique des
    mesures product_level de la cuve, et persiste les livraisons non encore
    connues (idempotent via la contrainte d'unicité tankId+startTime).

    Aucun endpoint HTTP n'appelle cette fonction (contrat Point 2 §3.3 :
    « aucun endpoint de création manuelle ») — elle simule ici le
    traitement de fond que produirait un scheduler réel, hors périmètre de
    cette API (même limite déjà actée pour TankMeasurement/HolykellDeviceRegistry,
    alimentés par la synchronisation Holykell, elle aussi hors périmètre)."""
    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == "product_level"
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]
    if not sensor_ids:
        return []

    measurements_result = await db.execute(
        select(TankMeasurement.measuredAt, TankMeasurement.rawValue)
        .where(TankMeasurement.hkSensorId.in_(sensor_ids))
        .order_by(TankMeasurement.measuredAt)
    )
    measurements = [(measuredAt, float(rawValue)) for measuredAt, rawValue in measurements_result.all()]
    events = detect_deliveries(measurements)
    if not events:
        return []

    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank_id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]

    existing_result = await db.execute(select(DeliveryDetected.startTime).where(DeliveryDetected.tankId == tank_id))
    existing_start_times = {row[0] for row in existing_result.all()}

    created = []
    for event in events:
        if event["startTime"] in existing_start_times:
            continue
        start_volume = interpolate_height_to_volume(calibration_points, event["startHeightMm"]) if calibration_points else None
        end_volume = interpolate_height_to_volume(calibration_points, event["endHeightMm"]) if calibration_points else None
        volume = (end_volume - start_volume) if (start_volume is not None and end_volume is not None) else None
        delivery = DeliveryDetected(
            tankId=tank_id,
            startTime=event["startTime"],
            startHeightMm=event["startHeightMm"],
            startVolumeLiters=start_volume,
            endTime=event["endTime"],
            endHeightMm=event["endHeightMm"],
            endVolumeLiters=end_volume,
            volumeLiters=volume,
        )
        db.add(delivery)
        created.append(delivery)

    if created:
        await db.commit()
        for delivery in created:
            await db.refresh(delivery)
    return created


def _delivery_to_response(delivery: DeliveryDetected, tank: Tank) -> DeliveryDetectedResponse:
    return DeliveryDetectedResponse(
        id=delivery.id,
        tankId=delivery.tankId,
        stationId=tank.stationId,
        startTime=delivery.startTime,
        startHeightMm=float(delivery.startHeightMm),
        endTime=delivery.endTime,
        endHeightMm=float(delivery.endHeightMm),
        volumeLiters=float(delivery.volumeLiters) if delivery.volumeLiters is not None else None,
    )


async def list_deliveries(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    from_date,
    to_date,
) -> Page:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    stmt = (
        select(DeliveryDetected, Tank)
        .join(Tank, Tank.id == DeliveryDetected.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if station_id is not None:
        stmt = stmt.where(Tank.stationId == station_id)
    if tank_id is not None:
        stmt = stmt.where(DeliveryDetected.tankId == tank_id)
    if from_date is not None:
        stmt = stmt.where(DeliveryDetected.startTime >= from_date)
    if to_date is not None:
        stmt = stmt.where(DeliveryDetected.startTime <= to_date)
    stmt = stmt.order_by(DeliveryDetected.startTime.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    data = [_delivery_to_response(delivery, tank) for delivery, tank in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def get_delivery(db: AsyncSession, organization_id: uuid.UUID, delivery_id: uuid.UUID) -> DeliveryDetectedResponse:
    result = await db.execute(
        select(DeliveryDetected, Tank)
        .join(Tank, Tank.id == DeliveryDetected.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(DeliveryDetected.id == delivery_id, Station.organizationId == organization_id)
    )
    row = result.first()
    if row is None:
        raise AppError(code="delivery_not_found", message="Livraison introuvable.", status_code=404)
    delivery, tank = row
    return _delivery_to_response(delivery, tank)


async def get_holykell_account_sync_status(db: AsyncSession, organization_id: uuid.UUID, account_id: uuid.UUID) -> HolykellAccount:
    result = await db.execute(
        select(HolykellAccount).where(HolykellAccount.id == account_id, HolykellAccount.organizationId == organization_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AppError(code="holykell_account_not_found", message="Compte Holykell introuvable.", status_code=404)
    return account
