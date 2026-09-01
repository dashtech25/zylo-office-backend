import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.zylo_liquid import service
from app.modules.zylo_liquid.models import FuelProduct, HolykellAccount, Station, Tank, TankSensorMapping
from app.modules.zylo_liquid.permissions import (
    FUEL_PRODUCT_MANAGE,
    FUEL_PRODUCT_READ,
    HOLYKELL_ACCOUNT_READ,
    STATION_MANAGE,
    STATION_READ,
    TANK_CALIBRATION_MANAGE,
    TANK_CALIBRATION_READ,
    TANK_MANAGE,
    TANK_READ,
    TANK_SENSOR_MAPPING_MANAGE,
    TANK_SENSOR_MAPPING_READ,
)
from app.modules.zylo_liquid.schemas import (
    CreateFuelProductRequest,
    CreateStationRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    FuelProductResponse,
    HolykellAccountSyncStatusResponse,
    ReplaceTankCalibrationPointsRequest,
    ReplaceTankCalibrationPointsResponse,
    StationResponse,
    TankCalibrationPointResponse,
    TankResponse,
    TankSensorMappingResponse,
    UpdateFuelProductRequest,
    UpdateStationRequest,
    UpdateTankRequest,
)
from app.modules_registry.service import require_module_active
from app.rbac.service import get_current_organization_id, require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter(dependencies=[Depends(require_module_active("zylo_liquid"))])


@router.post(
    "/fuel-products",
    response_model=FuelProductResponse,
    status_code=201,
    dependencies=[Depends(require_permission(FUEL_PRODUCT_MANAGE))],
)
async def create_fuel_product(
    data: CreateFuelProductRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> FuelProduct:
    return await service.create_fuel_product(db, organization_id, data)


@router.get(
    "/fuel-products",
    response_model=Page[FuelProductResponse],
    dependencies=[Depends(require_permission(FUEL_PRODUCT_READ))],
)
async def list_fuel_products(
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    stmt = select(FuelProduct).where(FuelProduct.organizationId == organization_id).order_by(FuelProduct.name)
    return await paginate(db, stmt, pagination, FuelProductResponse)


@router.get(
    "/fuel-products/{fuel_product_id}",
    response_model=FuelProductResponse,
    dependencies=[Depends(require_permission(FUEL_PRODUCT_READ))],
)
async def get_fuel_product(
    fuel_product_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> FuelProduct:
    return await service.get_fuel_product(db, organization_id, fuel_product_id)


@router.patch(
    "/fuel-products/{fuel_product_id}",
    response_model=FuelProductResponse,
    dependencies=[Depends(require_permission(FUEL_PRODUCT_MANAGE))],
)
async def update_fuel_product(
    fuel_product_id: uuid.UUID,
    data: UpdateFuelProductRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> FuelProduct:
    return await service.update_fuel_product(db, organization_id, fuel_product_id, data)


@router.post(
    "/stations",
    response_model=StationResponse,
    status_code=201,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
)
async def create_station(
    data: CreateStationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.create_station(db, organization_id, data)


@router.get(
    "/stations",
    response_model=Page[StationResponse],
    dependencies=[Depends(require_permission(STATION_READ))],
)
async def list_stations(
    pagination: PaginationParams = Depends(),
    cityId: uuid.UUID | None = None,
    status: str | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_stations(db, organization_id, pagination, cityId, status)


@router.get(
    "/stations/{station_id}",
    response_model=StationResponse,
    dependencies=[Depends(require_permission(STATION_READ))],
)
async def get_station(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.get_station(db, organization_id, station_id)


@router.patch(
    "/stations/{station_id}",
    response_model=StationResponse,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
)
async def update_station(
    station_id: uuid.UUID,
    data: UpdateStationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.update_station(db, organization_id, station_id, data)


@router.post(
    "/stations/{station_id}/deactivate",
    response_model=StationResponse,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
)
async def deactivate_station(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.deactivate_station(db, organization_id, station_id)


@router.post(
    "/stations/{station_id}/reactivate",
    response_model=StationResponse,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
)
async def reactivate_station(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.reactivate_station(db, organization_id, station_id)


@router.post(
    "/tanks",
    response_model=TankResponse,
    status_code=201,
    dependencies=[Depends(require_permission(TANK_MANAGE))],
)
async def create_tank(
    data: CreateTankRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Tank:
    return await service.create_tank(db, organization_id, data)


@router.get(
    "/tanks",
    response_model=Page[TankResponse],
    dependencies=[Depends(require_permission(TANK_READ))],
)
async def list_tanks(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    fuelProductId: uuid.UUID | None = None,
    active: bool | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_tanks(db, organization_id, pagination, stationId, fuelProductId, active)


@router.get(
    "/tanks/{tank_id}",
    response_model=TankResponse,
    dependencies=[Depends(require_permission(TANK_READ))],
)
async def get_tank(
    tank_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Tank:
    return await service.get_tank(db, organization_id, tank_id)


@router.patch(
    "/tanks/{tank_id}",
    response_model=TankResponse,
    dependencies=[Depends(require_permission(TANK_MANAGE))],
)
async def update_tank(
    tank_id: uuid.UUID,
    data: UpdateTankRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Tank:
    return await service.update_tank(db, organization_id, tank_id, data)


@router.post(
    "/tank-sensor-mappings",
    response_model=TankSensorMappingResponse,
    status_code=201,
    dependencies=[Depends(require_permission(TANK_SENSOR_MAPPING_MANAGE))],
)
async def create_tank_sensor_mapping(
    data: CreateTankSensorMappingRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TankSensorMapping:
    return await service.create_tank_sensor_mapping(db, organization_id, data)


@router.get(
    "/tank-sensor-mappings",
    response_model=Page[TankSensorMappingResponse],
    dependencies=[Depends(require_permission(TANK_SENSOR_MAPPING_READ))],
)
async def list_tank_sensor_mappings(
    pagination: PaginationParams = Depends(),
    tankId: uuid.UUID | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_tank_sensor_mappings(db, organization_id, pagination, tankId)


@router.post(
    "/tank-sensor-mappings/{mapping_id}/close",
    response_model=TankSensorMappingResponse,
    dependencies=[Depends(require_permission(TANK_SENSOR_MAPPING_MANAGE))],
)
async def close_tank_sensor_mapping(
    mapping_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TankSensorMapping:
    return await service.close_tank_sensor_mapping(db, organization_id, mapping_id)


@router.put(
    "/tanks/{tank_id}/calibration-points",
    response_model=ReplaceTankCalibrationPointsResponse,
    dependencies=[Depends(require_permission(TANK_CALIBRATION_MANAGE))],
)
async def replace_tank_calibration_points(
    tank_id: uuid.UUID,
    data: ReplaceTankCalibrationPointsRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReplaceTankCalibrationPointsResponse:
    points = await service.replace_tank_calibration_points(db, organization_id, tank_id, data)
    return ReplaceTankCalibrationPointsResponse(
        tankId=tank_id,
        pointCount=len(points),
        points=[TankCalibrationPointResponse.model_validate(p) for p in points],
    )


@router.get(
    "/tanks/{tank_id}/calibration-points",
    response_model=list[TankCalibrationPointResponse],
    dependencies=[Depends(require_permission(TANK_CALIBRATION_READ))],
)
async def list_tank_calibration_points(
    tank_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await service.list_tank_calibration_points(db, organization_id, tank_id)


@router.get(
    "/holykell-accounts/{account_id}/sync-status",
    response_model=HolykellAccountSyncStatusResponse,
    dependencies=[Depends(require_permission(HOLYKELL_ACCOUNT_READ))],
)
async def get_holykell_account_sync_status(
    account_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> HolykellAccount:
    return await service.get_holykell_account_sync_status(db, organization_id, account_id)
