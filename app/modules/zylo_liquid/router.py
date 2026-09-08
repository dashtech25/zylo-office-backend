import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid import service
from app.modules.zylo_liquid.algorithms import (
    DELIVERY_RISE_THRESHOLD_MM,
    DELIVERY_STABILITY_DELTA_MM,
    DELIVERY_STABILIZATION_MINUTES,
    LEAK_THRESHOLD_LPH,
)
from app.modules.zylo_liquid.models import FuelProduct, HolykellAccount, Station, Tank, TankSensorMapping
from app.modules.zylo_liquid.permissions import (
    ALERT_MANAGE,
    ALERT_READ,
    CASH_READ,
    DELIVERY_READ,
    FUEL_PRODUCT_MANAGE,
    FUEL_PRODUCT_READ,
    HOLYKELL_ACCOUNT_READ,
    LEAK_EVENT_READ,
    PRICE_HISTORY_CREATE,
    PRICE_HISTORY_READ,
    STATION_FUEL_PRODUCT_MANAGE,
    STATION_FUEL_PRODUCT_READ,
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
    AuthorizationResponse,
    CarrierResponse,
    CommercialAccountResponse,
    CreateAuthorizationRequest,
    CreateCarrierRequest,
    CreateCommercialAccountRequest,
    CreateDeliveryDeclarationRequest,
    CreateDocumentLinkRequest,
    CreateDocumentRequest,
    CreateDriverRequest,
    ReconciliationRecordResponse,
    StationReconciliationSettingsResponse,
    UpsertStationReconciliationSettingsRequest,
    CreateFuelProductRequest,
    CreateIncidentDeclarationRequest,
    CreateLeakTestDeclarationRequest,
    CreateManualGaugingDeclarationRequest,
    CreatePaymentRequest,
    CreatePurchaseOrderRequest,
    CreateQualityCheckDeclarationRequest,
    CreateSaleRequest,
    CreateShiftCashDeclarationRequest,
    CreateStationFuelProductRequest,
    CreateStationRequest,
    CreateSupplierRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    CreateTruckRequest,
    CreateVehicleRequest,
    AlertResponse,
    CreatePriceHistoryRequest,
    DeliveryDeclarationResponse,
    DeliveryDetectedResponse,
    DocumentLinkResponse,
    DocumentResponse,
    DriverResponse,
    FuelProductResponse,
    IncidentDeclarationResponse,
    LeakEventResponse,
    LeakTestDeclarationResponse,
    ManualGaugingDeclarationResponse,
    PaymentResponse,
    PriceHistoryResponse,
    PurchaseOrderResponse,
    QualityCheckDeclarationResponse,
    ReceivableResponse,
    ResolveAlertRequest,
    SaleResponse,
    ShiftCashDeclarationResponse,
    StationFuelProductResponse,
    SupplierResponse,
    TruckResponse,
    UpdateCarrierRequest,
    UpdateCommercialAccountRequest,
    UpdateDeliveryDeclarationRequest,
    UpdateIncidentDeclarationRequest,
    UpdateLeakTestDeclarationRequest,
    UpdateManualGaugingDeclarationRequest,
    UpdatePriceHistoryRequest,
    UpdateQualityCheckDeclarationRequest,
    UpdateShiftCashDeclarationRequest,
    UpdateStationFuelProductRequest,
    VehicleResponse,
    HolykellAccountSyncStatusResponse,
    NetworkCashSummaryResponse,
    NetworkSummaryResponse,
    StationCashDetailResponse,
    TankCashResponse,
    ReplaceTankCalibrationPointsRequest,
    ReplaceTankCalibrationPointsResponse,
    DeliveryInProgressResponse,
    StationCurrentStateResponse,
    StationResponse,
    SystemDefaultsResponse,
    TankCalibrationPointResponse,
    TankCurrentStateResponse,
    TankMeasurementResponse,
    TankResponse,
    TankSensorMappingResponse,
    UpdateFuelProductRequest,
    UpdateStationRequest,
    UpdateSupplierRequest,
    UpdateTankRequest,
    UpdateTruckRequest,
    AssignInterventionRequest,
    CloseInterventionRequest,
    CreateEquipmentRequest,
    CreateInterventionRequest,
    CreateProductSaleTransactionRequest,
    CreateRegulatoryDeclarationRequest,
    CreateRegulatoryDocumentRequest,
    CreateSellableProductRequest,
    CreateTechnicianRequest,
    EquipmentResponse,
    InterventionResponse,
    ProductSaleTransactionResponse,
    RegulatoryDeclarationResponse,
    RegulatoryDocumentResponse,
    SellableProductResponse,
    TechnicianResponse,
    UpdateEquipmentRequest,
    UpdateSellableProductRequest,
)
from app.modules_registry.service import require_module_active
from app.rbac.service import get_current_organization_id, require_permission, require_permission_scoped, require_permission_scoped_via
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page


async def _tank_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Une cuve n'a pas de portée propre dans le modèle de grants (§10.3 du
    document d'architecture RBAC) : la portée utile est celle de SA station
    (ex. « le chef d'équipe reçoit Cuve Diesel » = un grant scopé à la
    station qui la contient), jamais la cuve isolément."""
    raw_id = path_params.get("tank_id")
    if raw_id is None:
        return None, None
    tank = await service.get_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", tank.stationId


async def _alert_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("alert_id")
    if raw_id is None:
        return None, None
    _alert, tank = await service._get_alert_and_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", tank.stationId


async def _delivery_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("delivery_id")
    if raw_id is None:
        return None, None
    delivery = await service.get_delivery(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", delivery.stationId


async def _leak_event_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("leak_event_id")
    if raw_id is None:
        return None, None
    leak_event = await service.get_leak_event(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", leak_event.stationId


async def _price_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Un prix par défaut réseau (`stationId IS NULL`, Phase 1 §1.3 de
    refonte-configuration-zylo-liquid.md) n'a pas de station à laquelle
    rattacher la portée — `(None, None)` équivaut alors à une vérification
    org entière (comportement inchangé pour ces lignes)."""
    raw_id = path_params.get("price_id")
    if raw_id is None:
        return None, None
    price = await service._get_price_history_and_station(db, organization_id, uuid.UUID(str(raw_id)))
    if price.stationId is None:
        return None, None
    return "station", price.stationId


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
    "/station-fuel-products",
    response_model=StationFuelProductResponse,
    status_code=201,
    dependencies=[Depends(require_permission(STATION_FUEL_PRODUCT_MANAGE))],
)
async def create_station_fuel_product(
    data: CreateStationFuelProductRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_station_fuel_product(db, organization_id, data)


@router.get(
    "/station-fuel-products",
    response_model=Page[StationFuelProductResponse],
    dependencies=[Depends(require_permission(STATION_FUEL_PRODUCT_READ))],
)
async def list_station_fuel_products(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    fuelProductId: uuid.UUID | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_station_fuel_products(db, organization_id, pagination, stationId, fuelProductId)


@router.patch(
    "/station-fuel-products/{association_id}",
    response_model=StationFuelProductResponse,
    dependencies=[Depends(require_permission(STATION_FUEL_PRODUCT_MANAGE))],
)
async def update_station_fuel_product(
    association_id: uuid.UUID,
    data: UpdateStationFuelProductRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_station_fuel_product(db, organization_id, association_id, data)


@router.post(
    "/stations",
    response_model=StationResponse,
    status_code=201,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
)
async def create_station(
    data: CreateStationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.create_station(db, organization_id, current_user.id, data)


@router.get(
    "/stations",
    response_model=Page[StationResponse],
)
async def list_stations(
    pagination: PaginationParams = Depends(),
    cityId: uuid.UUID | None = None,
    status: str | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(STATION_READ)` en dépendance globale : la
    vérification ET le filtrage par portée sont faits ensemble dans
    `service.list_stations` (un simple 403/liste-vide binaire ne suffit pas
    ici, un gérant scopé doit voir SA station, pas rien)."""
    return await service.list_stations(db, organization_id, current_user.id, pagination, cityId, status)


@router.get(
    "/stations/{station_id}",
    response_model=StationResponse,
    dependencies=[Depends(require_permission_scoped(STATION_READ, "station", "station_id"))],
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
    dependencies=[Depends(require_permission_scoped(STATION_MANAGE, "station", "station_id"))],
)
async def update_station(
    station_id: uuid.UUID,
    data: UpdateStationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.update_station(db, organization_id, current_user.id, station_id, data)


@router.post(
    "/stations/{station_id}/deactivate",
    response_model=StationResponse,
    dependencies=[Depends(require_permission_scoped(STATION_MANAGE, "station", "station_id"))],
)
async def deactivate_station(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.deactivate_station(db, organization_id, current_user.id, station_id)


@router.post(
    "/stations/{station_id}/reactivate",
    response_model=StationResponse,
    dependencies=[Depends(require_permission_scoped(STATION_MANAGE, "station", "station_id"))],
)
async def reactivate_station(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Station:
    return await service.reactivate_station(db, organization_id, current_user.id, station_id)


@router.post(
    "/tanks",
    response_model=TankResponse,
    status_code=201,
    dependencies=[Depends(require_permission(TANK_MANAGE))],
)
async def create_tank(
    data: CreateTankRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tank:
    return await service.create_tank(db, organization_id, current_user.id, data)


@router.get(
    "/tanks",
    response_model=Page[TankResponse],
)
async def list_tanks(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    fuelProductId: uuid.UUID | None = None,
    active: bool | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_tanks(db, organization_id, current_user.id, pagination, stationId, fuelProductId, active)


@router.get(
    "/tanks/{tank_id}",
    response_model=TankResponse,
    dependencies=[Depends(require_permission_scoped_via(TANK_READ, _tank_station_scope))],
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
    dependencies=[Depends(require_permission_scoped_via(TANK_MANAGE, _tank_station_scope))],
)
async def update_tank(
    tank_id: uuid.UUID,
    data: UpdateTankRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tank:
    return await service.update_tank(db, organization_id, current_user.id, tank_id, data)


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
    "/tanks/{tank_id}/current-state",
    response_model=TankCurrentStateResponse,
    dependencies=[Depends(require_permission(TANK_READ))],
)
async def get_tank_current_state(
    tank_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TankCurrentStateResponse:
    return await service.get_tank_current_state_by_id(db, organization_id, tank_id)


@router.get(
    "/stations/{station_id}/current-state",
    response_model=StationCurrentStateResponse,
    dependencies=[Depends(require_permission(STATION_READ))],
)
async def get_station_current_state(
    station_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationCurrentStateResponse:
    return await service.get_station_current_state(db, organization_id, station_id)


@router.get(
    "/tanks/{tank_id}/measurements",
    response_model=Page[TankMeasurementResponse],
    dependencies=[Depends(require_permission(TANK_READ))],
)
async def list_tank_measurements(
    tank_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_tank_measurements(db, organization_id, tank_id, pagination, fromDate, toDate)


@router.get(
    "/network/summary",
    response_model=NetworkSummaryResponse,
    dependencies=[Depends(require_permission(STATION_READ))],
)
async def get_network_summary(
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> NetworkSummaryResponse:
    return await service.get_network_summary(db, organization_id, fromDate, toDate)


@router.get(
    "/network/snapshot",
    response_model=NetworkSummaryResponse,
    dependencies=[Depends(require_permission(STATION_READ))],
)
async def get_network_snapshot(
    at: datetime,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> NetworkSummaryResponse:
    return await service.get_network_snapshot(db, organization_id, at)


@router.get(
    "/deliveries",
    response_model=Page[DeliveryDetectedResponse],
)
async def list_deliveries(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    tankId: uuid.UUID | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(DELIVERY_READ)` en dépendance globale — la
    vérification ET le filtrage par portée sont faits ensemble dans
    `service.list_deliveries` (même principe que `list_stations`)."""
    return await service.list_deliveries(db, organization_id, current_user.id, pagination, stationId, tankId, fromDate, toDate)


@router.get(
    "/deliveries/{delivery_id}",
    response_model=DeliveryDetectedResponse,
    dependencies=[Depends(require_permission_scoped_via(DELIVERY_READ, _delivery_station_scope))],
)
async def get_delivery(
    delivery_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDetectedResponse:
    return await service.get_delivery(db, organization_id, delivery_id)


@router.get(
    "/deliveries-in-progress",
    response_model=list[DeliveryInProgressResponse],
    dependencies=[Depends(require_permission(DELIVERY_READ))],
)
async def list_deliveries_in_progress(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryInProgressResponse]:
    return await service.list_deliveries_in_progress(db, organization_id)


@router.get(
    "/leak-events",
    response_model=Page[LeakEventResponse],
)
async def list_leak_events(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    tankId: uuid.UUID | None = None,
    result: str | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(LEAK_EVENT_READ)` global — même principe
    que `list_stations`/`list_deliveries`."""
    return await service.list_leak_events(db, organization_id, current_user.id, pagination, stationId, tankId, result, fromDate, toDate)


@router.get(
    "/leak-events/{leak_event_id}",
    response_model=LeakEventResponse,
    dependencies=[Depends(require_permission_scoped_via(LEAK_EVENT_READ, _leak_event_station_scope))],
)
async def get_leak_event(
    leak_event_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> LeakEventResponse:
    return await service.get_leak_event(db, organization_id, leak_event_id)


@router.get(
    "/alerts",
    response_model=Page[AlertResponse],
)
async def list_alerts(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    tankId: uuid.UUID | None = None,
    type: str | None = None,
    status: str | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(ALERT_READ)` global — même principe que
    `list_stations`/`list_deliveries`/`list_leak_events`."""
    return await service.list_alerts(db, organization_id, current_user.id, pagination, stationId, tankId, type, status, fromDate, toDate)


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission_scoped_via(ALERT_READ, _alert_station_scope))],
)
async def get_alert(
    alert_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    return await service.get_alert(db, organization_id, alert_id)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission_scoped_via(ALERT_MANAGE, _alert_station_scope))],
)
async def resolve_alert(
    alert_id: uuid.UUID,
    data: ResolveAlertRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    return await service.resolve_alert(db, organization_id, current_user.id, alert_id, data.resolutionNote)


@router.post(
    "/prices",
    response_model=PriceHistoryResponse,
    status_code=201,
)
async def create_price_history(
    data: CreatePriceHistoryRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryResponse:
    return await service.create_price_history(db, organization_id, current_user.id, data)


@router.get(
    "/prices",
    response_model=Page[PriceHistoryResponse],
)
async def list_price_history(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    fuelProductId: uuid.UUID | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(PRICE_HISTORY_READ)` en dépendance globale —
    même raison que `list_stations` : la vérification ET le filtrage par
    portée station (Phase 4 §4) sont faits ensemble dans
    `service.list_price_history`."""
    return await service.list_price_history(db, organization_id, current_user.id, pagination, stationId, fuelProductId, fromDate, toDate)


@router.get(
    "/prices/{price_id}",
    response_model=PriceHistoryResponse,
    dependencies=[Depends(require_permission_scoped_via(PRICE_HISTORY_READ, _price_station_scope))],
)
async def get_price_history(
    price_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryResponse:
    return await service.get_price_history(db, organization_id, price_id)


@router.patch(
    "/prices/{price_id}",
    response_model=PriceHistoryResponse,
    dependencies=[Depends(require_permission_scoped_via(PRICE_HISTORY_CREATE, _price_station_scope))],
)
async def update_price_history(
    price_id: uuid.UUID,
    data: UpdatePriceHistoryRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryResponse:
    return await service.update_price_history(db, organization_id, price_id, data)


@router.get(
    "/holykell-accounts",
    response_model=list[HolykellAccountSyncStatusResponse],
    dependencies=[Depends(require_permission(HOLYKELL_ACCOUNT_READ))],
)
async def list_holykell_accounts(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[HolykellAccount]:
    return await service.list_holykell_accounts(db, organization_id)


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


@router.get("/system-defaults", response_model=SystemDefaultsResponse)
async def get_system_defaults(_: User = Depends(get_current_user)) -> SystemDefaultsResponse:
    """Constantes de `algorithms.py`, en lecture seule — page Paramètres >
    Système. Pas de scoping par organisation : ce sont des constantes
    globales du système, identiques pour tout le monde."""
    return SystemDefaultsResponse(
        leakThresholdLph=LEAK_THRESHOLD_LPH,
        deliveryRiseThresholdMm=DELIVERY_RISE_THRESHOLD_MM,
        deliveryStabilityDeltaMm=DELIVERY_STABILITY_DELTA_MM,
        deliveryStabilizationMinutes=DELIVERY_STABILIZATION_MINUTES,
    )


@router.get(
    "/cash/network-summary",
    response_model=NetworkCashSummaryResponse,
    dependencies=[Depends(require_permission(CASH_READ))],
)
async def get_network_cash_summary(
    fromDate: datetime,
    toDate: datetime,
    mode: str = "calendar",
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> NetworkCashSummaryResponse:
    return await service.get_network_cash_summary(db, organization_id, fromDate, toDate, mode)


@router.get(
    "/cash/stations/{station_id}",
    response_model=StationCashDetailResponse,
    dependencies=[Depends(require_permission_scoped(CASH_READ, "station", "station_id"))],
)
async def get_station_cash_detail(
    station_id: uuid.UUID,
    fromDate: datetime,
    toDate: datetime,
    mode: str = "calendar",
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationCashDetailResponse:
    return await service.get_station_cash_detail(db, organization_id, station_id, fromDate, toDate, mode)


@router.get(
    "/cash/tanks/{tank_id}",
    response_model=TankCashResponse,
    dependencies=[Depends(require_permission_scoped_via(CASH_READ, _tank_station_scope))],
)
async def get_tank_cash(
    tank_id: uuid.UUID,
    fromDate: datetime,
    toDate: datetime,
    mode: str = "calendar",
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TankCashResponse:
    return await service.get_tank_cash(db, organization_id, tank_id, fromDate, toDate, mode)


# ================================================================
# Couche déclarative (processus-double-sources-verite, Phase 5-8) — Bloc 2.
# Pas de `dependencies=[Depends(require_permission(...))]` sur ces routes :
# `stationId` vient du corps de la requête (create) ou n'est pas garanti
# avant lecture (update/lock, résolu depuis la déclaration elle-même) —
# même raison déjà documentée pour `POST /prices` (Configuration carburant,
# Phase 4 §4 de refonte-configuration-zylo-liquid.md) : la vérification ET
# le filtrage par portée station sont faits ensemble dans le service.
# ================================================================


@router.post("/delivery-declarations", response_model=DeliveryDeclarationResponse, status_code=201)
async def create_delivery_declaration(
    data: CreateDeliveryDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDeclarationResponse:
    return await service.create_delivery_declaration(db, organization_id, current_user.id, data)


@router.get("/delivery-declarations", response_model=Page[DeliveryDeclarationResponse])
async def list_delivery_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_delivery_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/delivery-declarations/{declaration_id}", response_model=DeliveryDeclarationResponse)
async def update_delivery_declaration(
    declaration_id: uuid.UUID,
    data: UpdateDeliveryDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDeclarationResponse:
    return await service.update_delivery_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/delivery-declarations/{declaration_id}/lock", response_model=DeliveryDeclarationResponse)
async def lock_delivery_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDeclarationResponse:
    return await service.lock_delivery_declaration(db, organization_id, current_user.id, declaration_id)


# ================================================================
# Couche Approvisionnement (fusion prototype #/livraisons avec la couche
# réelle). Pas de `dependencies=[Depends(require_permission(...))]` — même
# règle que la Couche Commercial : la vérification de portée (organisation
# entière pour les référentiels, station pour les commandes) est faite dans
# le service (Phase 7 §2).
# ================================================================


@router.post("/suppliers", response_model=SupplierResponse, status_code=201)
async def create_supplier(
    data: CreateSupplierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SupplierResponse:
    return await service.create_supplier(db, organization_id, current_user.id, data)


@router.get("/suppliers", response_model=Page[SupplierResponse])
async def list_suppliers(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_suppliers(db, organization_id, current_user.id, pagination)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: uuid.UUID,
    data: UpdateSupplierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SupplierResponse:
    return await service.update_supplier(db, organization_id, current_user.id, supplier_id, data)


@router.post("/carriers", response_model=CarrierResponse, status_code=201)
async def create_carrier(
    data: CreateCarrierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CarrierResponse:
    return await service.create_carrier(db, organization_id, current_user.id, data)


@router.get("/carriers", response_model=Page[CarrierResponse])
async def list_carriers(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_carriers(db, organization_id, current_user.id, pagination)


@router.patch("/carriers/{carrier_id}", response_model=CarrierResponse)
async def update_carrier(
    carrier_id: uuid.UUID,
    data: UpdateCarrierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CarrierResponse:
    return await service.update_carrier(db, organization_id, current_user.id, carrier_id, data)


@router.post("/trucks", response_model=TruckResponse, status_code=201)
async def create_truck(
    data: CreateTruckRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckResponse:
    return await service.create_truck(db, organization_id, current_user.id, data)


@router.get("/trucks", response_model=Page[TruckResponse])
async def list_trucks(
    pagination: PaginationParams = Depends(),
    carrierId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_trucks(db, organization_id, current_user.id, pagination, carrierId)


@router.patch("/trucks/{truck_id}", response_model=TruckResponse)
async def update_truck(
    truck_id: uuid.UUID,
    data: UpdateTruckRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckResponse:
    return await service.update_truck(db, organization_id, current_user.id, truck_id, data)


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order(
    data: CreatePurchaseOrderRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderResponse:
    return await service.create_purchase_order(db, organization_id, current_user.id, data)


@router.get("/purchase-orders", response_model=Page[PurchaseOrderResponse])
async def list_purchase_orders(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_purchase_orders(db, organization_id, current_user.id, pagination, stationId)


@router.get("/purchase-orders/{purchase_order_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    purchase_order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderResponse:
    return await service.get_purchase_order(db, organization_id, current_user.id, purchase_order_id)


@router.post("/shift-cash-declarations", response_model=ShiftCashDeclarationResponse, status_code=201)
async def create_shift_cash_declaration(
    data: CreateShiftCashDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftCashDeclarationResponse:
    return await service.create_shift_cash_declaration(db, organization_id, current_user.id, data)


@router.get("/shift-cash-declarations", response_model=Page[ShiftCashDeclarationResponse])
async def list_shift_cash_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_shift_cash_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/shift-cash-declarations/{declaration_id}", response_model=ShiftCashDeclarationResponse)
async def update_shift_cash_declaration(
    declaration_id: uuid.UUID,
    data: UpdateShiftCashDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftCashDeclarationResponse:
    return await service.update_shift_cash_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/shift-cash-declarations/{declaration_id}/lock", response_model=ShiftCashDeclarationResponse)
async def lock_shift_cash_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftCashDeclarationResponse:
    return await service.lock_shift_cash_declaration(db, organization_id, current_user.id, declaration_id)


@router.post("/manual-gauging-declarations", response_model=ManualGaugingDeclarationResponse, status_code=201)
async def create_manual_gauging_declaration(
    data: CreateManualGaugingDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ManualGaugingDeclarationResponse:
    return await service.create_manual_gauging_declaration(db, organization_id, current_user.id, data)


@router.get("/manual-gauging-declarations", response_model=Page[ManualGaugingDeclarationResponse])
async def list_manual_gauging_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_manual_gauging_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/manual-gauging-declarations/{declaration_id}", response_model=ManualGaugingDeclarationResponse)
async def update_manual_gauging_declaration(
    declaration_id: uuid.UUID,
    data: UpdateManualGaugingDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ManualGaugingDeclarationResponse:
    return await service.update_manual_gauging_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/manual-gauging-declarations/{declaration_id}/lock", response_model=ManualGaugingDeclarationResponse)
async def lock_manual_gauging_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ManualGaugingDeclarationResponse:
    return await service.lock_manual_gauging_declaration(db, organization_id, current_user.id, declaration_id)


@router.post("/quality-check-declarations", response_model=QualityCheckDeclarationResponse, status_code=201)
async def create_quality_check_declaration(
    data: CreateQualityCheckDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> QualityCheckDeclarationResponse:
    return await service.create_quality_check_declaration(db, organization_id, current_user.id, data)


@router.get("/quality-check-declarations", response_model=Page[QualityCheckDeclarationResponse])
async def list_quality_check_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_quality_check_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/quality-check-declarations/{declaration_id}", response_model=QualityCheckDeclarationResponse)
async def update_quality_check_declaration(
    declaration_id: uuid.UUID,
    data: UpdateQualityCheckDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> QualityCheckDeclarationResponse:
    return await service.update_quality_check_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/quality-check-declarations/{declaration_id}/lock", response_model=QualityCheckDeclarationResponse)
async def lock_quality_check_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> QualityCheckDeclarationResponse:
    return await service.lock_quality_check_declaration(db, organization_id, current_user.id, declaration_id)


@router.post("/leak-test-declarations", response_model=LeakTestDeclarationResponse, status_code=201)
async def create_leak_test_declaration(
    data: CreateLeakTestDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> LeakTestDeclarationResponse:
    return await service.create_leak_test_declaration(db, organization_id, current_user.id, data)


@router.get("/leak-test-declarations", response_model=Page[LeakTestDeclarationResponse])
async def list_leak_test_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_leak_test_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/leak-test-declarations/{declaration_id}", response_model=LeakTestDeclarationResponse)
async def update_leak_test_declaration(
    declaration_id: uuid.UUID,
    data: UpdateLeakTestDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> LeakTestDeclarationResponse:
    return await service.update_leak_test_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/leak-test-declarations/{declaration_id}/lock", response_model=LeakTestDeclarationResponse)
async def lock_leak_test_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> LeakTestDeclarationResponse:
    return await service.lock_leak_test_declaration(db, organization_id, current_user.id, declaration_id)


@router.post("/incident-declarations", response_model=IncidentDeclarationResponse, status_code=201)
async def create_incident_declaration(
    data: CreateIncidentDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> IncidentDeclarationResponse:
    return await service.create_incident_declaration(db, organization_id, current_user.id, data)


@router.get("/incident-declarations", response_model=Page[IncidentDeclarationResponse])
async def list_incident_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_incident_declarations(db, organization_id, current_user.id, pagination, stationId)


@router.patch("/incident-declarations/{declaration_id}", response_model=IncidentDeclarationResponse)
async def update_incident_declaration(
    declaration_id: uuid.UUID,
    data: UpdateIncidentDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> IncidentDeclarationResponse:
    return await service.update_incident_declaration(db, organization_id, current_user.id, declaration_id, data)


@router.post("/incident-declarations/{declaration_id}/lock", response_model=IncidentDeclarationResponse)
async def lock_incident_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> IncidentDeclarationResponse:
    return await service.lock_incident_declaration(db, organization_id, current_user.id, declaration_id)


# ================================================================
# Couche Commercial (processus-double-sources-verite, Phase 5-8) — Bloc 3/4.
# Pas de `dependencies=[Depends(require_permission(...))]` : la vérification
# de portée (organisation entière ou station selon la ressource) est faite
# dans le service (Phase 7 §2), même raison déjà documentée plus haut.
# ================================================================


@router.post("/commercial-accounts", response_model=CommercialAccountResponse, status_code=201)
async def create_commercial_account(
    data: CreateCommercialAccountRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CommercialAccountResponse:
    return await service.create_commercial_account(db, organization_id, current_user.id, data)


@router.get("/commercial-accounts", response_model=Page[CommercialAccountResponse])
async def list_commercial_accounts(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_commercial_accounts(db, organization_id, current_user.id, pagination)


@router.patch("/commercial-accounts/{account_id}", response_model=CommercialAccountResponse)
async def update_commercial_account(
    account_id: uuid.UUID,
    data: UpdateCommercialAccountRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CommercialAccountResponse:
    return await service.update_commercial_account(db, organization_id, current_user.id, account_id, data)


@router.post("/vehicles", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    data: CreateVehicleRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    return await service.create_vehicle(db, organization_id, current_user.id, data)


@router.post("/drivers", response_model=DriverResponse, status_code=201)
async def create_driver(
    data: CreateDriverRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DriverResponse:
    return await service.create_driver(db, organization_id, current_user.id, data)


@router.post("/authorizations", response_model=AuthorizationResponse, status_code=201)
async def create_authorization(
    data: CreateAuthorizationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> AuthorizationResponse:
    return await service.create_authorization(db, organization_id, current_user.id, data)


@router.post("/sales", response_model=SaleResponse, status_code=201)
async def create_sale(
    data: CreateSaleRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SaleResponse:
    return await service.create_sale(db, organization_id, current_user.id, data)


@router.get("/sales", response_model=Page[SaleResponse])
async def list_sales(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_sales(db, organization_id, current_user.id, pagination, stationId)


@router.get("/receivables", response_model=Page[ReceivableResponse])
async def list_receivables(
    pagination: PaginationParams = Depends(),
    commercialAccountId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_receivables(db, organization_id, current_user.id, pagination, commercialAccountId)


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(
    data: CreatePaymentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    return await service.create_payment(db, organization_id, current_user.id, data)


@router.get("/payments", response_model=Page[PaymentResponse])
async def list_payments(
    pagination: PaginationParams = Depends(),
    receivableId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_payments(db, organization_id, current_user.id, pagination, receivableId)


# ================================================================
# Modèle documentaire (processus-double-sources-verite, Phase 5 §6) — Bloc 5.
# ================================================================


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    data: CreateDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    return await service.create_document(db, organization_id, current_user.id, data)


@router.post("/document-links", response_model=DocumentLinkResponse, status_code=201)
async def create_document_link(
    data: CreateDocumentLinkRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentLinkResponse:
    return await service.create_document_link(db, organization_id, current_user.id, data)


@router.get("/documents/by-entity", response_model=list[DocumentResponse])
async def list_documents_for_entity(
    linkedEntityType: str,
    linkedEntityId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    return await service.list_document_links_for_entity(db, organization_id, current_user.id, linkedEntityType, linkedEntityId)


@router.delete("/documents/{document_id}", response_model=DocumentResponse)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    return await service.delete_document(db, organization_id, current_user.id, document_id)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 5 : catalogue de
# produits vendables.
# ================================================================


@router.post("/sellable-products", response_model=SellableProductResponse, status_code=201)
async def create_sellable_product(
    data: CreateSellableProductRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SellableProductResponse:
    return await service.create_sellable_product(db, organization_id, current_user.id, data)


@router.patch("/sellable-products/{product_id}", response_model=SellableProductResponse)
async def update_sellable_product(
    product_id: uuid.UUID,
    data: UpdateSellableProductRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SellableProductResponse:
    return await service.update_sellable_product(db, organization_id, current_user.id, product_id, data)


@router.get("/sellable-products", response_model=Page[SellableProductResponse])
async def list_sellable_products(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_sellable_products(db, organization_id, current_user.id, pagination, stationId, search)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 4 (corrigé) : ventes de
# produits boutique — entité séparée de `Sale` (voir models.py).
# ================================================================


@router.post("/product-sales", response_model=ProductSaleTransactionResponse, status_code=201)
async def create_product_sale_transaction(
    data: CreateProductSaleTransactionRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ProductSaleTransactionResponse:
    return await service.create_product_sale_transaction(db, organization_id, current_user.id, data)


@router.post("/product-sales/{transaction_id}/cancel", response_model=ProductSaleTransactionResponse)
async def cancel_product_sale_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ProductSaleTransactionResponse:
    return await service.cancel_product_sale_transaction(db, organization_id, current_user.id, transaction_id)


@router.get("/product-sales", response_model=Page[ProductSaleTransactionResponse])
async def list_product_sale_transactions(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_product_sale_transactions(db, organization_id, current_user.id, pagination, stationId)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 6 : Maintenance.
# ================================================================


@router.post("/technicians", response_model=TechnicianResponse, status_code=201)
async def create_technician(
    data: CreateTechnicianRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TechnicianResponse:
    return await service.create_technician(db, organization_id, current_user.id, data)


@router.get("/technicians", response_model=Page[TechnicianResponse])
async def list_technicians(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_technicians(db, organization_id, current_user.id, pagination)


@router.post("/equipment", response_model=EquipmentResponse, status_code=201)
async def create_equipment(
    data: CreateEquipmentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await service.create_equipment(db, organization_id, current_user.id, data)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: uuid.UUID,
    data: UpdateEquipmentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await service.update_equipment(db, organization_id, current_user.id, equipment_id, data)


@router.get("/equipment", response_model=Page[EquipmentResponse])
async def list_equipment(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_equipment(db, organization_id, current_user.id, pagination, stationId)


@router.post("/interventions", response_model=InterventionResponse, status_code=201)
async def create_intervention(
    data: CreateInterventionRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> InterventionResponse:
    return await service.create_intervention(db, organization_id, current_user.id, data)


@router.post("/interventions/{intervention_id}/assign", response_model=InterventionResponse)
async def assign_intervention(
    intervention_id: uuid.UUID,
    data: AssignInterventionRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> InterventionResponse:
    return await service.assign_intervention(db, organization_id, current_user.id, intervention_id, data)


@router.post("/interventions/{intervention_id}/close", response_model=InterventionResponse)
async def close_intervention(
    intervention_id: uuid.UUID,
    data: CloseInterventionRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> InterventionResponse:
    return await service.close_intervention(db, organization_id, current_user.id, intervention_id, data)


@router.get("/interventions", response_model=Page[InterventionResponse])
async def list_interventions(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_interventions(db, organization_id, current_user.id, pagination, stationId)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 7 : Réglementation.
# ================================================================


@router.post("/regulatory-documents", response_model=RegulatoryDocumentResponse, status_code=201)
async def create_regulatory_document(
    data: CreateRegulatoryDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> RegulatoryDocumentResponse:
    return await service.create_regulatory_document(db, organization_id, current_user.id, data)


@router.post("/regulatory-documents/{document_id}/renew", response_model=RegulatoryDocumentResponse)
async def renew_regulatory_document(
    document_id: uuid.UUID,
    data: CreateRegulatoryDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> RegulatoryDocumentResponse:
    return await service.renew_regulatory_document(db, organization_id, current_user.id, document_id, data)


@router.get("/regulatory-documents", response_model=Page[RegulatoryDocumentResponse])
async def list_regulatory_documents(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    needsActionOnly: bool = False,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_regulatory_documents(db, organization_id, current_user.id, pagination, stationId, needsActionOnly)


@router.post("/regulatory-declarations", response_model=RegulatoryDeclarationResponse, status_code=201)
async def create_regulatory_declaration(
    data: CreateRegulatoryDeclarationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> RegulatoryDeclarationResponse:
    return await service.create_regulatory_declaration(db, organization_id, current_user.id, data)


@router.get("/regulatory-declarations", response_model=Page[RegulatoryDeclarationResponse])
async def list_regulatory_declarations(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_regulatory_declarations(db, organization_id, current_user.id, pagination, stationId)


# ================================================================
# Rapprochement (processus-double-sources-verite, Phase 6, Phase 7 §1) —
# Bloc 6.
# ================================================================


@router.get("/stations/{station_id}/reconciliation-settings", response_model=StationReconciliationSettingsResponse | None)
async def get_station_reconciliation_settings(
    station_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationReconciliationSettingsResponse | None:
    return await service.get_station_reconciliation_settings(db, organization_id, current_user.id, station_id)


@router.put("/stations/{station_id}/reconciliation-settings", response_model=StationReconciliationSettingsResponse)
async def upsert_station_reconciliation_settings(
    station_id: uuid.UUID,
    data: UpsertStationReconciliationSettingsRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationReconciliationSettingsResponse:
    return await service.upsert_station_reconciliation_settings(db, organization_id, current_user.id, station_id, data)


@router.get("/reconciliation-records", response_model=Page[ReconciliationRecordResponse])
async def list_reconciliation_records(
    pagination: PaginationParams = Depends(),
    subjectType: str | None = None,
    subjectId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_reconciliation_records(db, organization_id, current_user.id, pagination, subjectType, subjectId)


# ================================================================
# Mécanisme de calcul du rapprochement (processus-double-sources-verite,
# Phase 6 §3-5) — Bloc 7. Calcul paresseux, déclenché à la demande.
# ================================================================


@router.post("/delivery-declarations/{declaration_id}/reconcile", response_model=ReconciliationRecordResponse)
async def reconcile_delivery_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRecordResponse:
    return await service.evaluate_delivery_declaration_reconciliation(db, organization_id, current_user.id, declaration_id)


@router.post("/manual-gauging-declarations/{declaration_id}/reconcile", response_model=ReconciliationRecordResponse)
async def reconcile_manual_gauging_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRecordResponse:
    return await service.evaluate_manual_gauging_declaration_reconciliation(db, organization_id, current_user.id, declaration_id)


@router.post("/quality-check-declarations/{declaration_id}/reconcile", response_model=ReconciliationRecordResponse)
async def reconcile_quality_check_declaration(
    declaration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRecordResponse:
    return await service.evaluate_quality_check_declaration_reconciliation(db, organization_id, current_user.id, declaration_id)


@router.post("/tanks/{tank_id}/reconcile-stock", response_model=ReconciliationRecordResponse)
async def reconcile_stock(
    tank_id: uuid.UUID,
    day: date,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRecordResponse:
    return await service.evaluate_stock_reconciliation(db, organization_id, current_user.id, tank_id, day)
