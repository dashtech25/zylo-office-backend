"""Cuves : cuves, pompes, correspondances capteurs (sensor mappings), points de calibration.

Responsabilité : CRUD des cuves et des pompes, rattachement d'un capteur à une cuve, calibration.
N'y appartiennent pas : état courant et mesures des cuves, livraisons, fuites, alertes, caisse
(restent dans `service.py` pour les lots suivants). Dépend de `stations/`, jamais l'inverse.
`service.py` réexporte ces fonctions : les anciens chemins restent valides.
"""

import uuid
from datetime import date, datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.modules.zylo_liquid.permissions import TANK_READ, PUMP_READ
from app.rbac.service import list_visible_resource_ids
from app.modules.zylo_liquid.models import (
    HolykellDeviceRegistry,
    Pump,
    Station,
    Tank,
    TankCalibrationPoint,
    TankSensorMapping,
)
from app.modules.zylo_liquid.stations.schemas import CreateFuelProductRequest
from app.modules.zylo_liquid.tanks.schemas import (
    CreatePumpRequest,
    UpdatePumpRequest,
    PumpResponse,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    HolykellSensorLiveState,
    ReplaceTankCalibrationPointsRequest,
    TankResponse,
    TankSensorMappingResponse,
    UpdateTankRequest,
)
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta
from app.modules.zylo_liquid.stations.service import create_fuel_product, get_fuel_product, get_station


async def create_tank(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateTankRequest) -> Tank:
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
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.tank.create",
        entity_type="Tank",
        entity_id=tank.id,
        summary=f"Création de la cuve {tank.displayName}",
        scope_resource_type="station",
        scope_resource_id=tank.stationId,
    )
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


_TANK_PRODUCT_UPDATE_FIELDS = {"fuelProductId", "newFuelProductName", "newFuelProductCode"}


async def update_tank(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, tank_id: uuid.UUID, data: UpdateTankRequest
) -> Tank:
    tank = await get_tank(db, organization_id, tank_id)
    updates = data.model_dump(exclude_unset=True, exclude=_TANK_PRODUCT_UPDATE_FIELDS)
    before = {field: getattr(tank, field) for field in updates}
    for field, value in updates.items():
        setattr(tank, field, value)

    # Changement de produit carburant (P0-1, audit module Stations
    # 2026-09-16) — traité à part du reste car il exige de résoudre/créer un
    # FuelProduct, exactement comme `create_tank` : soit un produit
    # existant, soit un nouveau créé à la volée, jamais aucun des deux ni les
    # deux à la fois. `productSince` n'est mis à jour que si le produit
    # résolu diffère réellement de l'actuel, pour ne jamais réinitialiser
    # cette date lors d'une simple modification de seuils.
    has_existing_product = data.fuelProductId is not None
    has_new_product = data.newFuelProductName is not None or data.newFuelProductCode is not None
    if has_existing_product or has_new_product:
        if has_existing_product and has_new_product:
            raise AppError(
                code="fuel_product_selection_invalid",
                message="Fournir soit fuelProductId, soit newFuelProductName + newFuelProductCode — jamais les deux.",
                status_code=422,
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
        if fuel_product.id != tank.fuelProductId:
            before["fuelProductId"] = tank.fuelProductId
            updates["fuelProductId"] = fuel_product.id
            tank.fuelProductId = fuel_product.id
            tank.productSince = date.today()

    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.tank.update",
        entity_type="Tank",
        entity_id=tank.id,
        summary=f"Modification de la cuve {tank.displayName}",
        changes={field: {"before": str(before[field]), "after": str(updates[field])} for field in updates},
        scope_resource_type="station",
        scope_resource_id=tank.stationId,
    )
    await db.commit()
    await db.refresh(tank)
    return tank


async def list_tanks(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    fuel_product_id: uuid.UUID | None,
    active: bool | None,
) -> Page:
    """Une cuve n'a pas de portée propre : filtrée par la STATION visible de
    l'utilisateur (même principe que `list_stations`, `_tank_station_scope`
    au niveau vérification) — un gérant/pompiste scopé à une station ne voit
    ici que les cuves de celle-ci."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, TANK_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {TANK_READ}.", status_code=403)

    stmt = select(Tank).join(Station, Station.id == Tank.stationId).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(Tank.stationId.in_(visible_station_ids))
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


async def create_pump(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreatePumpRequest) -> Pump:
    await get_station(db, organization_id, data.stationId)  # lève station_not_found si hors périmètre
    tank = await get_tank(db, organization_id, data.tankId)
    if tank.stationId != data.stationId:
        raise AppError(
            code="pump_tank_station_mismatch",
            message="La cuve sélectionnée n'appartient pas à la station de la pompe.",
            status_code=422,
        )

    pump = Pump(stationId=data.stationId, tankId=data.tankId, name=data.name)
    db.add(pump)
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.pump.create",
        entity_type="Pump",
        entity_id=pump.id,
        summary=f"Création de la pompe {pump.name}",
        scope_resource_type="station",
        scope_resource_id=pump.stationId,
    )
    await db.commit()
    await db.refresh(pump)
    return pump


async def _assert_pump_station_in_organization(db: AsyncSession, organization_id: uuid.UUID, pump: Pump) -> None:
    result = await db.execute(
        select(Station.id).where(Station.id == pump.stationId, Station.organizationId == organization_id)
    )
    if result.scalar_one_or_none() is None:
        raise AppError(code="pump_not_found", message="Pompe introuvable.", status_code=404)


async def get_pump(db: AsyncSession, organization_id: uuid.UUID, pump_id: uuid.UUID) -> Pump:
    result = await db.execute(select(Pump).where(Pump.id == pump_id))
    pump = result.scalar_one_or_none()
    if pump is None:
        raise AppError(code="pump_not_found", message="Pompe introuvable.", status_code=404)
    await _assert_pump_station_in_organization(db, organization_id, pump)
    return pump


async def update_pump(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pump_id: uuid.UUID, data: UpdatePumpRequest
) -> Pump:
    pump = await get_pump(db, organization_id, pump_id)
    updates = data.model_dump(exclude_unset=True)

    if "tankId" in updates and updates["tankId"] is not None:
        tank = await get_tank(db, organization_id, updates["tankId"])
        if tank.stationId != pump.stationId:
            raise AppError(
                code="pump_tank_station_mismatch",
                message="La cuve sélectionnée n'appartient pas à la station de la pompe.",
                status_code=422,
            )

    before = {field: getattr(pump, field) for field in updates}
    for field, value in updates.items():
        setattr(pump, field, value)

    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.pump.update",
        entity_type="Pump",
        entity_id=pump.id,
        summary=f"Modification de la pompe {pump.name}",
        changes={field: {"before": str(before[field]), "after": str(updates[field])} for field in updates},
        scope_resource_type="station",
        scope_resource_id=pump.stationId,
    )
    await db.commit()
    await db.refresh(pump)
    return pump


async def list_pumps(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    active: bool | None,
) -> Page:
    """Une pompe n'a pas de portée propre : filtrée par la STATION visible de
    l'utilisateur, même principe que `list_tanks`/`_tank_station_scope`."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, PUMP_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PUMP_READ}.", status_code=403)

    stmt = select(Pump).join(Station, Station.id == Pump.stationId).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(Pump.stationId.in_(visible_station_ids))
    if station_id is not None:
        stmt = stmt.where(Pump.stationId == station_id)
    if active is not None:
        stmt = stmt.where(Pump.active.is_(active))
    stmt = stmt.order_by(Pump.name)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    pumps = result.scalars().all()
    data = [PumpResponse.model_validate(pump) for pump in pumps]
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

    # Enrichissement de chaque mapping avec l'état *mesuré* du sensor côté
    # registre Holykell (dernière valeur, dernière visibilité, statut
    # remonté par l'équipement) : une seule requête pour tous les sensors de
    # la page, jamais N+1. Un sensor absent du registre (mapping sans
    # découverte Holykell) reste `live: null` — pas d'état inventé.
    sensor_ids = [mapping.hkSensorId for mapping in mappings]
    registry_by_sensor_id: dict[int, HolykellDeviceRegistry] = {}
    if sensor_ids:
        registry_rows = await db.execute(
            select(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId.in_(sensor_ids))
        )
        registry_by_sensor_id = {row.hkSensorId: row for row in registry_rows.scalars().all()}

    data = []
    for mapping in mappings:
        item = TankSensorMappingResponse.model_validate(mapping)
        registry = registry_by_sensor_id.get(mapping.hkSensorId)
        if registry is not None:
            item.live = HolykellSensorLiveState(
                hkSerialNumber=registry.hkSerialNumber,
                hkSensorName=registry.hkSensorName,
                hkUnit=registry.hkUnit,
                hkReportCycleSec=registry.hkReportCycleSec,
                hkLastStatus=registry.hkLastStatus,
                hkLastSeenAt=registry.hkLastSeenAt,
                lastValue=registry.lastValue,
                lastValueAt=registry.lastValueAt,
                syncFrom=registry.syncFrom,
            )
        data.append(item)
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
