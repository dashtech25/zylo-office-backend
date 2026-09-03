import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_liquid.algorithms import (
    compute_leak_rate_lph,
    compute_net_corrected_volume,
    correct_volume_to_reference_temperature,
    detect_deliveries,
    evaluate_threshold_alarms,
    interpolate_height_to_volume,
    is_leak_detected,
)
from app.modules.zylo_liquid.models import (
    Alert,
    DeliveryDetected,
    FuelProduct,
    HolykellAccount,
    HolykellDeviceRegistry,
    LeakageRecord,
    PriceHistory,
    Station,
    Tank,
    TankCalibrationPoint,
    TankMeasurement,
    TankSensorMapping,
)
from app.modules.zylo_liquid.schemas import (
    AlertResponse,
    CreateFuelProductRequest,
    CreatePriceHistoryRequest,
    CreateStationRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    DeliveryDetectedResponse,
    LeakEventResponse,
    NetworkSummaryProductLine,
    NetworkSummaryResponse,
    PriceHistoryResponse,
    ReplaceTankCalibrationPointsRequest,
    StationCurrentStateResponse,
    StationResponse,
    TankCurrentStateResponse,
    TankMeasurementResponse,
    TankResponse,
    TankSensorMappingResponse,
    UpdateFuelProductRequest,
    UpdatePriceHistoryRequest,
    UpdateStationRequest,
    UpdateTankRequest,
)
from app.shared.currency import Currency
from app.shared.geo import City, Country, Region
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


async def _resolve_applicable_price(db: AsyncSession, station_id: uuid.UUID, fuel_product_id: uuid.UUID, at) -> PriceHistory | None:
    """Prix applicable à un instant donné (Point 2 §7.6, niveau_1_...md
    §16) : la ligne `PriceHistory` dont `effectiveFrom` est la plus récente
    antérieure ou égale à l'instant demandé — jamais un prix postérieur,
    jamais le prix courant en cache."""
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.stationId == station_id, PriceHistory.fuelProductId == fuel_product_id, PriceHistory.effectiveFrom <= at)
        .order_by(PriceHistory.effectiveFrom.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_tank_monetary_value(
    db: AsyncSession, tank: Tank, volume_liters: float | None, at
) -> tuple[float | None, str | None, str | None]:
    """Retourne (valeur, code devise, motif de non-calcul) — jamais un
    zéro quand le prix n'est pas connu (Point 2 §7.6)."""
    if volume_liters is None:
        return None, None, "volume_not_calculable"
    price = await _resolve_applicable_price(db, tank.stationId, tank.fuelProductId, at)
    if price is None:
        return None, None, "no_applicable_price"
    currency = await db.get(Currency, price.currencyId)
    return volume_liters * float(price.priceAmount), currency.code if currency else None, None


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
            monetaryValue=None,
            currencyCode=None,
            monetaryValueNotCalculableReason="volume_not_calculable",
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monetary_value, currency_code, monetary_reason = await _resolve_tank_monetary_value(db, tank, volume_net, now)

    return TankCurrentStateResponse(
        tankId=tank.id,
        tankNumber=tank.tankNumber,
        displayName=tank.displayName,
        sensorStatus=sensor_status,
        heightMm=height_mm,
        volumeLiters=volume_net,
        volumeNotCalculableReason=volume_not_calculable_reason,
        volumeLiters15C=volume_15c,
        monetaryValue=monetary_value,
        currencyCode=currency_code,
        monetaryValueNotCalculableReason=monetary_reason,
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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for tank in tanks:
        state = await get_tank_current_state(db, tank)
        if state.volumeLiters is None:
            continue  # cuve sans mesure calculable exclue du total (jamais un zéro, Point 2 §3.2)

        entry = _init_product_entry(per_product, tank.fuelProductId)
        entry["stations"].add(tank.stationId)
        entry["tanks"] += 1
        entry["volume"] += state.volumeLiters
        all_stations_with_data.add(tank.stationId)
        _accumulate_monetary(entry, state.monetaryValue, state.currencyCode)

    products = _build_product_lines(per_product, fuel_products_by_id)

    return NetworkSummaryResponse(
        products=products,
        totalVolumeLiters=sum(p.totalVolumeLiters for p in products),
        totalStationCount=len(all_stations_with_data),
        totalTankCount=sum(p.tankCount for p in products),
    )


def _init_product_entry(per_product: dict, fuel_product_id: uuid.UUID) -> dict:
    return per_product.setdefault(
        fuel_product_id, {"stations": set(), "tanks": 0, "volume": 0.0, "monetary": 0.0, "currencies": set(), "incomplete_pricing": False}
    )


def _accumulate_monetary(entry: dict, monetary_value: float | None, currency_code: str | None) -> None:
    if monetary_value is None:
        entry["incomplete_pricing"] = True
        return
    entry["monetary"] += monetary_value
    if currency_code is not None:
        entry["currencies"].add(currency_code)


def _build_product_lines(per_product: dict, fuel_products_by_id: dict) -> list[NetworkSummaryProductLine]:
    """Total monétaire par produit calculé uniquement si toutes les cuves
    de ce produit ont un prix applicable dans une seule et même devise —
    sinon la réponse l'indique explicitement, jamais une somme erronée
    entre devises différentes ou une valeur partielle silencieuse
    (Point 2 §7.6, niveau_1_...md §20)."""
    lines = []
    for fuel_product_id, entry in per_product.items():
        if entry["incomplete_pricing"]:
            monetary_value, currency_code, reason = None, None, "incomplete_pricing"
        elif len(entry["currencies"]) > 1:
            monetary_value, currency_code, reason = None, None, "mixed_currencies"
        elif len(entry["currencies"]) == 1:
            monetary_value, currency_code, reason = entry["monetary"], next(iter(entry["currencies"])), None
        else:
            monetary_value, currency_code, reason = None, None, "no_applicable_price"

        lines.append(
            NetworkSummaryProductLine(
                fuelProductId=fuel_product_id,
                fuelProductName=fuel_products_by_id[fuel_product_id].name if fuel_product_id in fuel_products_by_id else "?",
                totalVolumeLiters=entry["volume"],
                stationCount=len(entry["stations"]),
                tankCount=entry["tanks"],
                totalMonetaryValue=monetary_value,
                currencyCode=currency_code,
                monetaryValueNotCalculableReason=reason,
            )
        )
    return lines


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


async def _measurement_height_at(db: AsyncSession, tank_id: uuid.UUID, measurement_type: str, at_time) -> float | None:
    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == measurement_type
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]
    if not sensor_ids:
        return None
    result = await db.execute(
        select(TankMeasurement.rawValue).where(TankMeasurement.hkSensorId.in_(sensor_ids), TankMeasurement.measuredAt == at_time)
    )
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None


async def run_leak_test_for_tank(db: AsyncSession, tank_id: uuid.UUID, start_time, end_time) -> LeakageRecord:
    """Test de fuite statique explicite (Point 10 §10.3, version finale
    corrigée EPA) — contrairement aux livraisons (scan continu de tout
    l'historique), un test de fuite porte sur une fenêtre précise choisie
    (station à l'arrêt), jamais détecté en continu. Idempotent via la
    contrainte tankId+startTime+endTime."""
    if start_time >= end_time:
        raise AppError(code="invalid_test_window", message="startTime doit être strictement antérieure à endTime.", status_code=422)

    existing = await db.execute(
        select(LeakageRecord).where(
            LeakageRecord.tankId == tank_id, LeakageRecord.startTime == start_time, LeakageRecord.endTime == end_time
        )
    )
    existing_record = existing.scalar_one_or_none()
    if existing_record is not None:
        return existing_record

    start_height = await _measurement_height_at(db, tank_id, "product_level", start_time)
    end_height = await _measurement_height_at(db, tank_id, "product_level", end_time)
    if start_height is None or end_height is None:
        raise AppError(
            code="measurement_not_found_for_window",
            message="Aucune mesure product_level exacte trouvée au début ou à la fin de la fenêtre de test.",
            status_code=422,
        )

    start_water = await _measurement_height_at(db, tank_id, "water_level", start_time)
    end_water = await _measurement_height_at(db, tank_id, "water_level", end_time)
    start_temp = await _measurement_height_at(db, tank_id, "temperature", start_time)
    end_temp = await _measurement_height_at(db, tank_id, "temperature", end_time)

    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank_id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]

    tank_result = await db.execute(select(Tank).where(Tank.id == tank_id))
    tank = tank_result.scalar_one()
    fuel_product = await db.get(FuelProduct, tank.fuelProductId)
    alpha = float(fuel_product.thermalExpansionCoefficient) if fuel_product.thermalExpansionCoefficient is not None else None

    v_start = compute_net_corrected_volume(calibration_points, start_height, start_water, start_temp, alpha) if calibration_points else None
    v_end = compute_net_corrected_volume(calibration_points, end_height, end_water, end_temp, alpha) if calibration_points else None

    duration_hours = (end_time - start_time).total_seconds() / 3600
    leak_rate = compute_leak_rate_lph(v_start, v_end, duration_hours) if (v_start is not None and v_end is not None) else None
    result_value = "anomaly" if (leak_rate is not None and is_leak_detected(leak_rate)) else "normal"

    record = LeakageRecord(
        tankId=tank_id,
        startTime=start_time,
        startHeightMm=start_height,
        startWaterHeightMm=start_water,
        startTemperatureC=start_temp,
        endTime=end_time,
        endHeightMm=end_height,
        endWaterHeightMm=end_water,
        endTemperatureC=end_temp,
        leakRateLph=leak_rate,
        result=result_value,
    )
    db.add(record)
    await db.flush()

    if result_value == "anomaly":
        await _create_alert_if_not_already_active(
            db, tank_id, "leak", triggered_at=end_time, triggered_value=leak_rate, threshold_value=0.38
        )

    await db.commit()
    await db.refresh(record)
    return record


def _leak_event_to_response(record: LeakageRecord, tank: Tank) -> LeakEventResponse:
    return LeakEventResponse(
        id=record.id,
        tankId=record.tankId,
        stationId=tank.stationId,
        startTime=record.startTime,
        endTime=record.endTime,
        leakRateLph=float(record.leakRateLph) if record.leakRateLph is not None else None,
        result=record.result,
    )


async def list_leak_events(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    result_filter: str | None,
    from_date,
    to_date,
) -> Page:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    stmt = (
        select(LeakageRecord, Tank)
        .join(Tank, Tank.id == LeakageRecord.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if station_id is not None:
        stmt = stmt.where(Tank.stationId == station_id)
    if tank_id is not None:
        stmt = stmt.where(LeakageRecord.tankId == tank_id)
    if result_filter is not None:
        stmt = stmt.where(LeakageRecord.result == result_filter)
    if from_date is not None:
        stmt = stmt.where(LeakageRecord.startTime >= from_date)
    if to_date is not None:
        stmt = stmt.where(LeakageRecord.startTime <= to_date)
    stmt = stmt.order_by(LeakageRecord.startTime.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    data = [_leak_event_to_response(record, tank) for record, tank in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def get_leak_event(db: AsyncSession, organization_id: uuid.UUID, leak_event_id: uuid.UUID) -> LeakEventResponse:
    result = await db.execute(
        select(LeakageRecord, Tank)
        .join(Tank, Tank.id == LeakageRecord.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(LeakageRecord.id == leak_event_id, Station.organizationId == organization_id)
    )
    row = result.first()
    if row is None:
        raise AppError(code="leak_event_not_found", message="Événement de fuite introuvable.", status_code=404)
    record, tank = row
    return _leak_event_to_response(record, tank)


async def _create_alert_if_not_already_active(
    db: AsyncSession, tank_id: uuid.UUID, alert_type: str, triggered_at, triggered_value: float | None, threshold_value: float | None
) -> Alert | None:
    """N'ouvre jamais une deuxième alerte active du même type pour la même
    cuve — évite le spam ; la résolution reste manuelle (Point 2 §4.6)."""
    existing = await db.execute(
        select(Alert).where(Alert.tankId == tank_id, Alert.type == alert_type, Alert.status == "active")
    )
    if existing.scalar_one_or_none() is not None:
        return None
    alert = Alert(
        tankId=tank_id,
        type=alert_type,
        status="active",
        triggeredAt=triggered_at,
        triggeredValue=triggered_value,
        thresholdValue=threshold_value,
    )
    db.add(alert)
    await db.flush()
    return alert


async def run_alert_evaluation_for_tank(db: AsyncSession, tank_id: uuid.UUID) -> list[Alert]:
    """Évalue l'état instantané d'une cuve (mêmes sources que l'endpoint 7 :
    `HolykellDeviceRegistry.lastValue`/`hkLastStatus`, jamais `TankMeasurement`)
    contre les 4 seuils déjà saisis sur `Tank` (endpoint 3) — algorithme de
    Point 13 §13.4, jamais réimplémenté. Sonde déconnectée détectée via
    `hkLastStatus` déjà maintenu par la synchronisation Holykell, jamais un
    seuil d'ancienneté inventé (même principe que l'endpoint 7, issue #35)."""
    tank_result = await db.execute(select(Tank).where(Tank.id == tank_id))
    tank = tank_result.scalar_one()

    product_registry = await _get_active_registry_entry(db, tank_id, "product_level")
    created: list[Alert] = []

    if product_registry is None or product_registry.lastValue is None:
        return created

    if product_registry.hkLastStatus == 0:
        alert = await _create_alert_if_not_already_active(db, tank_id, "sensor_offline", datetime.now(timezone.utc).replace(tzinfo=None), None, None)
        if alert:
            created.append(alert)
        await db.commit()
        return created  # sonde déconnectée : aucune mesure fiable, pas de comparaison de seuils

    height = float(product_registry.lastValue)
    water_registry = await _get_active_registry_entry(db, tank_id, "water_level")
    water_height = float(water_registry.lastValue) if water_registry and water_registry.lastValue is not None else None

    triggered_types = evaluate_threshold_alarms(
        height_mm=height,
        water_height_mm=water_height,
        height_alarm_mm=float(tank.heightAlarmMm),
        height_alert_mm=float(tank.heightAlertMm),
        low_alarm_mm=float(tank.lowAlarmMm),
        water_alarm_mm=float(tank.alertWaterMaxMm),
    )

    threshold_by_type = {
        "level_high": float(tank.heightAlarmMm),
        "level_high_pre_alarm": float(tank.heightAlertMm),
        "level_low": float(tank.lowAlarmMm),
        "water": float(tank.alertWaterMaxMm),
    }
    value_by_type = {
        "level_high": height - (water_height or 0),
        "level_high_pre_alarm": height - (water_height or 0),
        "level_low": height - (water_height or 0),
        "water": water_height,
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for alert_type in triggered_types:
        alert = await _create_alert_if_not_already_active(
            db, tank_id, alert_type, now, value_by_type[alert_type], threshold_by_type[alert_type]
        )
        if alert:
            created.append(alert)

    if created:
        await db.commit()
    return created


def _alert_to_response(alert: Alert, tank: Tank) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        tankId=alert.tankId,
        stationId=tank.stationId,
        type=alert.type,
        status=alert.status,
        triggeredAt=alert.triggeredAt,
        triggeredValue=float(alert.triggeredValue) if alert.triggeredValue is not None else None,
        thresholdValue=float(alert.thresholdValue) if alert.thresholdValue is not None else None,
        resolvedAt=alert.resolvedAt,
        resolutionNote=alert.resolutionNote,
    )


async def list_alerts(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    type_filter: str | None,
    status_filter: str | None,
    from_date,
    to_date,
) -> Page:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    stmt = (
        select(Alert, Tank)
        .join(Tank, Tank.id == Alert.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if station_id is not None:
        stmt = stmt.where(Tank.stationId == station_id)
    if tank_id is not None:
        stmt = stmt.where(Alert.tankId == tank_id)
    if type_filter is not None:
        stmt = stmt.where(Alert.type == type_filter)
    if status_filter is not None:
        stmt = stmt.where(Alert.status == status_filter)
    if from_date is not None:
        stmt = stmt.where(Alert.triggeredAt >= from_date)
    if to_date is not None:
        stmt = stmt.where(Alert.triggeredAt <= to_date)
    stmt = stmt.order_by(Alert.triggeredAt.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    data = [_alert_to_response(alert, tank) for alert, tank in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _get_alert_and_tank(db: AsyncSession, organization_id: uuid.UUID, alert_id: uuid.UUID) -> tuple[Alert, Tank]:
    result = await db.execute(
        select(Alert, Tank)
        .join(Tank, Tank.id == Alert.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Alert.id == alert_id, Station.organizationId == organization_id)
    )
    row = result.first()
    if row is None:
        raise AppError(code="alert_not_found", message="Alerte introuvable.", status_code=404)
    return row


async def get_alert(db: AsyncSession, organization_id: uuid.UUID, alert_id: uuid.UUID) -> AlertResponse:
    alert, tank = await _get_alert_and_tank(db, organization_id, alert_id)
    return _alert_to_response(alert, tank)


async def resolve_alert(db: AsyncSession, organization_id: uuid.UUID, alert_id: uuid.UUID, resolution_note: str | None) -> AlertResponse:
    alert, tank = await _get_alert_and_tank(db, organization_id, alert_id)
    if alert.status == "resolved":
        raise AppError(code="alert_already_resolved", message="Cette alerte est déjà résolue.", status_code=409)
    alert.status = "resolved"
    alert.resolvedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    alert.resolutionNote = resolution_note
    await db.commit()
    await db.refresh(alert)
    return _alert_to_response(alert, tank)


async def _measurement_at_or_before(db: AsyncSession, tank_id: uuid.UUID, measurement_type: str, at) -> float | None:
    """Dernière mesure connue avant ou égale à l'instant demandé, jamais une
    mesure postérieure (Point 2 §5.4)."""
    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == measurement_type
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]
    if not sensor_ids:
        return None
    result = await db.execute(
        select(TankMeasurement.rawValue)
        .where(TankMeasurement.hkSensorId.in_(sensor_ids), TankMeasurement.measuredAt <= at)
        .order_by(TankMeasurement.measuredAt.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None


async def get_network_snapshot(db: AsyncSession, organization_id: uuid.UUID, at) -> NetworkSummaryResponse:
    """État reconstitué du réseau à un instant passé (Point 2 §5.4) — même
    structure de réponse que l'endpoint 9 (network/summary), mais résolue
    depuis l'historique `TankMeasurement` plutôt que depuis
    `HolykellDeviceRegistry.lastValue` (instant présent). Réutilise
    `interpolate_height_to_volume`, déjà validé à l'endpoint 7."""
    # `at` peut arriver "aware" (ex. suffixe Z, ISO 8601 UTC standard envoyé
    # par le frontend) alors que le reste du module compare uniquement des
    # datetimes naïves en UTC (convention déjà établie, cf. `now` ci-dessous)
    # — sans cette normalisation, la comparaison suivante lève TypeError
    # dès qu'un client envoie un datetime avec fuseau explicite (bug réel,
    # pas une adaptation de contrat : Point 2 §5.4 exige déjà l'UTC ISO 8601).
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if at > now:
        raise AppError(code="snapshot_date_in_future", message="La date demandée ne peut pas être dans le futur.", status_code=422)

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
        height = await _measurement_at_or_before(db, tank.id, "product_level", at)
        if height is None:
            continue  # aucune mesure avant l'instant demandé -> cuve exclue, jamais un zéro (Point 2 §5.4)

        calibration_result = await db.execute(
            select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank.id)
        )
        calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]
        if not calibration_points:
            continue  # volume non calculable -> cuve exclue

        volume_brut = interpolate_height_to_volume(calibration_points, height)
        water_height = await _measurement_at_or_before(db, tank.id, "water_level", at)
        water_volume = interpolate_height_to_volume(calibration_points, water_height) if water_height is not None else 0.0
        volume_net = volume_brut - water_volume

        entry = _init_product_entry(per_product, tank.fuelProductId)
        entry["stations"].add(tank.stationId)
        entry["tanks"] += 1
        entry["volume"] += volume_net
        all_stations_with_data.add(tank.stationId)

        monetary_value, currency_code, _ = await _resolve_tank_monetary_value(db, tank, volume_net, at)
        _accumulate_monetary(entry, monetary_value, currency_code)

    products = _build_product_lines(per_product, fuel_products_by_id)

    return NetworkSummaryResponse(
        products=products,
        totalVolumeLiters=sum(p.totalVolumeLiters for p in products),
        totalStationCount=len(all_stations_with_data),
        totalTankCount=sum(p.tankCount for p in products),
    )


async def _resolve_station_default_currency(db: AsyncSession, station: Station) -> Currency:
    """Devise par défaut d'une station : Station.cityId -> City -> Region ->
    Country.currencyCode (chaîne déjà existante) -> Currency correspondante
    (endpoint 14). Jamais une devise inventée si la chaîne est incomplète
    ou si la Currency n'existe pas encore (Point 2 Chapitre 7 introduction,
    niveau_1_...md §17-18)."""
    if station.cityId is None:
        raise AppError(
            code="station_currency_not_resolvable",
            message="Cette station n'a pas de ville associée — impossible de déduire sa devise par défaut ; fournir explicitement currencyId.",
            status_code=422,
        )
    city_result = await db.execute(select(City).where(City.id == station.cityId))
    city = city_result.scalar_one_or_none()
    region = (await db.execute(select(Region).where(Region.id == city.regionId))).scalar_one_or_none() if city else None
    country = (await db.execute(select(Country).where(Country.id == region.countryId))).scalar_one_or_none() if region else None
    if country is None:
        raise AppError(
            code="station_currency_not_resolvable",
            message="Chaîne géographique incomplète pour cette station — impossible de déduire sa devise par défaut ; fournir explicitement currencyId.",
            status_code=422,
        )
    currency_result = await db.execute(select(Currency).where(Currency.code == country.currencyCode))
    currency = currency_result.scalar_one_or_none()
    if currency is None:
        raise AppError(
            code="currency_not_found",
            message=f"La devise par défaut de cette station ('{country.currencyCode}') n'existe pas encore dans le référentiel — la créer via POST /currencies avant d'enregistrer un prix.",
            status_code=422,
        )
    return currency


async def create_price_history(
    db: AsyncSession, organization_id: uuid.UUID, created_by: uuid.UUID, data: CreatePriceHistoryRequest
) -> PriceHistoryResponse:
    station = await get_station(db, organization_id, data.stationId)
    await get_fuel_product(db, organization_id, data.fuelProductId)

    if data.currencyId is not None:
        currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
        if currency_result.scalar_one_or_none() is None:
            raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
        currency_id = data.currencyId
    else:
        currency = await _resolve_station_default_currency(db, station)
        currency_id = currency.id

    # `effectiveFrom` est une colonne TIMESTAMP WITHOUT TIME ZONE (comme le
    # reste du schéma télémétrie/référentiel) — un datetime timezone-aware
    # envoyé par un client réel (ISO 8601 avec "Z"/offset, cas normal de
    # tout appelant HTTP) fait échouer la comparaison SQL avec asyncpg
    # ("can't subtract offset-naive and offset-aware datetimes"). Normalisé
    # en UTC naïf, même pattern déjà appliqué à `is_future` plus bas.
    effective_from = data.effectiveFrom
    if effective_from.tzinfo is not None:
        effective_from = effective_from.astimezone(timezone.utc).replace(tzinfo=None)

    existing = await db.execute(
        select(PriceHistory).where(
            PriceHistory.stationId == data.stationId,
            PriceHistory.fuelProductId == data.fuelProductId,
            PriceHistory.effectiveFrom == effective_from,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="price_conflict_same_period",
            message="Une ligne de prix existe déjà pour cette station, ce produit et cette date de début.",
            status_code=409,
        )

    price = PriceHistory(
        stationId=data.stationId,
        fuelProductId=data.fuelProductId,
        currencyId=currency_id,
        priceAmount=data.priceAmount,
        costAmount=data.costAmount,
        effectiveFrom=effective_from,
        changeReason=data.changeReason,
        createdBy=created_by,
    )
    db.add(price)
    await db.commit()
    await db.refresh(price)

    is_future = price.effectiveFrom > datetime.now(timezone.utc).replace(tzinfo=None)
    return PriceHistoryResponse.model_validate(price).model_copy(update={"isFuture": is_future})


async def _get_price_history_and_station(db: AsyncSession, organization_id: uuid.UUID, price_id: uuid.UUID) -> PriceHistory:
    result = await db.execute(
        select(PriceHistory)
        .join(Station, Station.id == PriceHistory.stationId)
        .where(PriceHistory.id == price_id, Station.organizationId == organization_id)
    )
    price = result.scalar_one_or_none()
    if price is None:
        raise AppError(code="price_history_not_found", message="Ligne de prix introuvable.", status_code=404)
    return price


async def update_price_history(
    db: AsyncSession, organization_id: uuid.UUID, price_id: uuid.UUID, data: UpdatePriceHistoryRequest
) -> PriceHistoryResponse:
    """Correction ciblée uniquement — jamais la période, la station ou le
    produit (Point 2 §7.4) : `UpdatePriceHistoryRequest` ne les expose pas,
    garantissant par construction qu'aucune autre ligne n'est jamais
    affectée."""
    price = await _get_price_history_and_station(db, organization_id, price_id)
    updates = data.model_dump(exclude_unset=True)
    if "currencyId" in updates and updates["currencyId"] is not None:
        currency_result = await db.execute(select(Currency).where(Currency.id == updates["currencyId"]))
        if currency_result.scalar_one_or_none() is None:
            raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
    for field, value in updates.items():
        setattr(price, field, value)
    await db.commit()
    await db.refresh(price)
    return PriceHistoryResponse.model_validate(price)


async def list_price_history(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    fuel_product_id: uuid.UUID | None,
    from_date,
    to_date,
) -> Page:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    stmt = (
        select(PriceHistory)
        .join(Station, Station.id == PriceHistory.stationId)
        .where(Station.organizationId == organization_id)
    )
    if station_id is not None:
        stmt = stmt.where(PriceHistory.stationId == station_id)
    if fuel_product_id is not None:
        stmt = stmt.where(PriceHistory.fuelProductId == fuel_product_id)
    if from_date is not None:
        stmt = stmt.where(PriceHistory.effectiveFrom >= from_date)
    if to_date is not None:
        stmt = stmt.where(PriceHistory.effectiveFrom <= to_date)
    stmt = stmt.order_by(PriceHistory.effectiveFrom.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    data = [PriceHistoryResponse.model_validate(row) for row in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def get_price_history(db: AsyncSession, organization_id: uuid.UUID, price_id: uuid.UUID) -> PriceHistoryResponse:
    price = await _get_price_history_and_station(db, organization_id, price_id)
    return PriceHistoryResponse.model_validate(price)


async def get_holykell_account_sync_status(db: AsyncSession, organization_id: uuid.UUID, account_id: uuid.UUID) -> HolykellAccount:
    result = await db.execute(
        select(HolykellAccount).where(HolykellAccount.id == account_id, HolykellAccount.organizationId == organization_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AppError(code="holykell_account_not_found", message="Compte Holykell introuvable.", status_code=404)
    return account
