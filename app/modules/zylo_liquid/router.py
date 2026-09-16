import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from starlette.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.security import get_current_user
from app.files.schemas import DocumentResponse
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
    GeneratePurchaseOrderDocumentRequest,
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
    CreatePriceHistoryRequest,
    DeliveryDeclarationResponse,
    DeliveryDetectedResponse,
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
    SaleResponse,
    ShiftCashDeclarationResponse,
    StationFuelProductResponse,
    UpdateStationFuelProductThresholdsRequest,
    StationFuelProductOverviewResponse,
    CreateStationServiceRequest,
    UpdateStationServiceRequest,
    StationServiceResponse,
    UpdatePricingPolicyRequest,
    PricingPolicyResponse,
    SupplierResponse,
    TruckResponse,
    TruckOrderAssignmentRequest,
    TruckOrderAssignmentResponse,
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
    UpdateRegulatoryDocumentRequest,
    UpdateSellableProductRequest,
    CreateSecurityEquipmentRequest,
    UpdateSecurityEquipmentRequest,
    SecurityEquipmentResponse,
    CreateStationSupplierRequest,
    UpdateStationSupplierRequest,
    StationSupplierResponse,
    UpdateStationFinancialRequest,
    StationFinancialResponse,
    CreateStationStaffRequest,
    UpdateStationStaffRequest,
    StationStaffResponse,
    CreateStationStaffResponse,
    ChangeStationStaffRoleRequest,
    ResetStationStaffPasswordResponse,
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


# _alert_station_scope — déplacée vers `app/alerts/router.py` (2026-09-15,
# Phase 3), avec les routes /alerts* qu'elle scope.


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
    # Cache TTL 60s : référentiel quasi statique, invalidé explicitement par
    # create_fuel_product/update_fuel_product (service.py) — jamais périmé
    # au-delà d'une écriture dans le même process (Phase 1 audit, pb #3).
    cache_key = f"org:{organization_id}:limit:{pagination.limit}:offset:{pagination.offset}"
    cached = service.fuel_product_list_cache.get(cache_key)
    if cached is not None:
        return cached
    stmt = select(FuelProduct).where(FuelProduct.organizationId == organization_id).order_by(FuelProduct.name)
    page = await paginate(db, stmt, pagination, FuelProductResponse)
    service.fuel_product_list_cache.set(cache_key, page)
    return page


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


# Page Exploitation (Centre administratif de la station) — vue d'ensemble
# carburants, seuils, services, politique commerciale par produit. Portée
# vérifiée dans le service (_check_declaration_scope), pas de dépendance
# require_permission ici — même convention que le reste du Centre
# administratif (SecurityEquipment, StationSupplier...).


@router.patch("/station-fuel-products/{association_id}/thresholds", response_model=StationFuelProductResponse)
async def update_station_fuel_product_thresholds(
    association_id: uuid.UUID,
    data: UpdateStationFuelProductThresholdsRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationFuelProductResponse:
    return await service.update_station_fuel_product_thresholds(db, organization_id, current_user.id, association_id, data)


@router.get(
    "/stations/{station_id}/fuel-products-overview",
    response_model=list[StationFuelProductOverviewResponse],
    summary="Vue d'ensemble des produits vendus par une station",
    description="Pour chaque produit rattaché à la station : prix courant, cuves associées et volume disponible agrégé. Pensé pour alimenter un écran de synthèse station sans agréger côté client.",
)
async def list_station_fuel_products_overview(
    station_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[StationFuelProductOverviewResponse]:
    return await service.list_station_fuel_products_overview(db, organization_id, current_user.id, station_id)


@router.post("/station-services", response_model=StationServiceResponse, status_code=201)
async def create_station_service(
    data: CreateStationServiceRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationServiceResponse:
    return await service.create_station_service(db, organization_id, current_user.id, data)


@router.patch("/station-services/{service_id}", response_model=StationServiceResponse)
async def update_station_service(
    service_id: uuid.UUID,
    data: UpdateStationServiceRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationServiceResponse:
    return await service.update_station_service(db, organization_id, current_user.id, service_id, data)


@router.get("/station-services", response_model=list[StationServiceResponse])
async def list_station_services(
    stationId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[StationServiceResponse]:
    return await service.list_station_services(db, organization_id, current_user.id, stationId)


@router.get("/station-product-pricing-policy", response_model=PricingPolicyResponse | None)
async def get_pricing_policy(
    stationId: uuid.UUID,
    fuelProductId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PricingPolicyResponse | None:
    return await service.get_pricing_policy(db, organization_id, current_user.id, stationId, fuelProductId)


@router.patch("/station-product-pricing-policy", response_model=PricingPolicyResponse)
async def update_pricing_policy(
    stationId: uuid.UUID,
    fuelProductId: uuid.UUID,
    data: UpdatePricingPolicyRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> PricingPolicyResponse:
    return await service.update_pricing_policy(db, organization_id, current_user.id, stationId, fuelProductId, data)


@router.post(
    "/stations",
    response_model=StationResponse,
    status_code=201,
    dependencies=[Depends(require_permission(STATION_MANAGE))],
    summary="Créer une station-service",
    description=(
        "Crée une nouvelle station dans l'organisation courante. La station est créée active par "
        "défaut ; ses cuves, produits et rattachements se paramètrent ensuite via les endpoints dédiés "
        "(`/tanks`, `/station-fuel-products`, etc.)."
    ),
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
    summary="Lister les stations de l'organisation",
    description=(
        "Liste paginée des stations, filtrable par ville et par statut. Le filtrage par portée "
        "(un utilisateur scopé à une station ne voit que la sienne) est appliqué directement dans "
        "`service.list_stations`, pas via une dépendance de permission globale."
    ),
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
    summary="Détail d'une station",
    description="Retourne une station par son identifiant. Accès scopé : nécessite une lecture accordée sur cette station précise (ou une portée plus large).",
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
    summary="Modifier une station",
    description="Met à jour partiellement les champs d'une station (seuls les champs fournis sont modifiés). N'affecte pas le statut actif/inactif — utiliser `/deactivate` ou `/reactivate` pour cela.",
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
    summary="Désactiver une station",
    description="Marque la station comme inactive sans la supprimer (les données historiques — livraisons, cuves, alertes — restent consultables). Une station désactivée peut être réactivée via `/reactivate`.",
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
    summary="Réactiver une station",
    description="Remet une station désactivée en statut actif.",
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
    summary="Créer une cuve",
    description=(
        "Crée une cuve rattachée à une station. La cuve n'a pas de portée RBAC propre : les droits "
        "s'évaluent via la station qui la contient (cf. `_tank_station_scope`). Le capteur de niveau "
        "se rattache séparément via `/tank-sensor-mappings`."
    ),
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
    summary="Lister les cuves",
    description="Liste paginée des cuves, filtrable par station, par produit et par statut actif/inactif.",
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
    summary="Détail d'une cuve",
    description="Retourne une cuve par son identifiant. Ne contient pas le niveau/volume courant — voir `/tanks/{tank_id}/current-state` pour l'état temps réel.",
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
    summary="Modifier une cuve",
    description="Met à jour partiellement les champs statiques d'une cuve (capacité, produit, seuils...). Ne modifie pas la table de jaugeage — voir `/tanks/{tank_id}/calibration-points` pour cela.",
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
    summary="Remplacer la table de jaugeage d'une cuve",
    description=(
        "Remplace intégralement la table de conversion hauteur (mm) → volume (L) utilisée pour "
        "convertir les mesures du capteur en volume de produit. Opération destructive : l'ancienne "
        "table est écrasée en une fois, il n'y a pas d'ajout incrémental."
    ),
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
    summary="Table de jaugeage d'une cuve",
    description="Retourne la table de conversion hauteur → volume actuellement active pour la cuve, triée par hauteur croissante.",
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
    dependencies=[Depends(require_permission_scoped_via(TANK_READ, _tank_station_scope))],
    summary="État courant d'une cuve",
    description=(
        "Dernier niveau connu de la cuve (hauteur, volume calculé via la table de jaugeage, "
        "pourcentage de remplissage) tel que remonté par le capteur, avec l'horodatage de la mesure."
    ),
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
    dependencies=[Depends(require_permission_scoped(STATION_READ, "station", "station_id"))],
    summary="État courant d'une station",
    description="Vue agrégée de l'état courant de toutes les cuves d'une station (niveaux, alertes actives), pratique pour un tableau de bord station sans multiplier les appels par cuve.",
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
    dependencies=[Depends(require_permission_scoped_via(TANK_READ, _tank_station_scope))],
    summary="Historique des mesures d'une cuve",
    description="Série temporelle paginée des relevés du capteur pour la cuve, filtrable par plage de dates. Contrairement à `/current-state`, expose l'historique complet, pas seulement le dernier point.",
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
    summary="Lister les livraisons détectées",
    description=(
        "Liste paginée des livraisons de carburant détectées automatiquement par l'algorithme de "
        "surveillance des cuves (montée de niveau + stabilisation, cf. `algorithms.py`), filtrable "
        "par station, cuve et plage de dates. Il s'agit de livraisons *détectées*, pas des déclarations "
        "manuelles du chauffeur — voir `/delivery-declarations` pour ces dernières."
    ),
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
    summary="Détail d'une livraison détectée",
    description="Retourne une livraison détectée par son identifiant, avec les volumes avant/après et la fenêtre temporelle de détection.",
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
    summary="Livraisons en cours de détection",
    description=(
        "Liste les montées de niveau en cours d'observation, pas encore confirmées comme livraison "
        "(le niveau doit rester stable pendant "
        "`DELIVERY_STABILIZATION_MINUTES` avant confirmation). Utile pour un affichage temps réel, "
        "ces entrées peuvent disparaître si la montée s'avère être du bruit de mesure plutôt qu'un "
        "remplissage réel."
    ),
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


# Routes /alerts* — déplacées vers `app/alerts/router.py` (2026-09-15,
# Phase 3 de la migration monolithe modulaire), montées sous le même
# préfixe `/zylo-liquid` (voir `app/api/v1/router.py`) : aucune URL ne
# change côté frontend.


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


@router.post(
    "/carriers",
    response_model=CarrierResponse,
    status_code=201,
    summary="Créer un transporteur",
    description="Enregistre un transporteur (société propriétaire ou affréteur des camions de livraison) pour l'organisation.",
)
async def create_carrier(
    data: CreateCarrierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CarrierResponse:
    return await service.create_carrier(db, organization_id, current_user.id, data)


@router.get(
    "/carriers",
    response_model=Page[CarrierResponse],
    summary="Lister les transporteurs",
    description="Liste paginée des transporteurs de l'organisation.",
)
async def list_carriers(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_carriers(db, organization_id, current_user.id, pagination)


@router.patch(
    "/carriers/{carrier_id}",
    response_model=CarrierResponse,
    summary="Modifier un transporteur",
    description="Met à jour partiellement les informations d'un transporteur.",
)
async def update_carrier(
    carrier_id: uuid.UUID,
    data: UpdateCarrierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CarrierResponse:
    return await service.update_carrier(db, organization_id, current_user.id, carrier_id, data)


@router.post(
    "/trucks",
    response_model=TruckResponse,
    status_code=201,
    summary="Créer un camion",
    description="Enregistre un camion-citerne rattaché à un transporteur. Le suivi GPS (boîtier, positions) se paramètre séparément via les endpoints `/gps-devices` et `/tracking-*`.",
)
async def create_truck(
    data: CreateTruckRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckResponse:
    return await service.create_truck(db, organization_id, current_user.id, data)


@router.get(
    "/trucks",
    response_model=Page[TruckResponse],
    summary="Lister les camions",
    description="Liste paginée des camions de l'organisation, filtrable par transporteur.",
)
async def list_trucks(
    pagination: PaginationParams = Depends(),
    carrierId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_trucks(db, organization_id, current_user.id, pagination, carrierId)


@router.patch(
    "/trucks/{truck_id}",
    response_model=TruckResponse,
    summary="Modifier un camion",
    description="Met à jour partiellement les informations d'un camion (immatriculation, transporteur, capacité...).",
)
async def update_truck(
    truck_id: uuid.UUID,
    data: UpdateTruckRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckResponse:
    return await service.update_truck(db, organization_id, current_user.id, truck_id, data)


# Tracking GPS des camions-citernes — routes déplacées vers
# `app/location/router.py` (2026-09-15, Phase 2) : /gps-devices*,
# /traccar-connection, /tracking-locations*, /truck-stop-reconciliations*,
# /truck-stops/{id}/comments, /truck-stop-comments/{id},
# /tracking-settings, /gps-ingest-credential*, /gps/ingest,
# /trucks/current-positions, /trucks/live-positions,
# /trucks/{id}/positions, /trucks/{id}/stops. Toujours montées sous le
# même préfixe /zylo-liquid (voir app/api/v1/router.py).



@router.post("/purchase-orders/{purchase_order_id}/trucks", response_model=TruckOrderAssignmentResponse, status_code=201)
async def assign_truck_to_purchase_order(
    purchase_order_id: uuid.UUID,
    data: TruckOrderAssignmentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckOrderAssignmentResponse:
    return await service.assign_truck_to_purchase_order(db, organization_id, current_user.id, purchase_order_id, data)


@router.delete("/purchase-orders/{purchase_order_id}/trucks/{truck_id}", status_code=204)
async def unassign_truck_from_purchase_order(
    purchase_order_id: uuid.UUID,
    truck_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.unassign_truck_from_purchase_order(db, organization_id, current_user.id, purchase_order_id, truck_id)


@router.get("/purchase-orders/{purchase_order_id}/trucks", response_model=list[TruckOrderAssignmentResponse])
async def list_trucks_for_purchase_order(
    purchase_order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckOrderAssignmentResponse]:
    return await service.list_trucks_for_purchase_order(db, organization_id, current_user.id, purchase_order_id)


@router.get(
    "/trucks/{truck_id}/orders",
    response_model=list[TruckOrderAssignmentResponse],
    summary="Bons de commande assignés à un camion",
    description="Liste les bons de commande (purchase orders) actuellement assignés à ce camion pour livraison.",
)
async def list_orders_for_truck(
    truck_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckOrderAssignmentResponse]:
    return await service.list_orders_for_truck(db, organization_id, current_user.id, truck_id)



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


@router.post("/purchase-orders/{purchase_order_id}/generate-document", response_model=DocumentResponse, status_code=201)
async def generate_purchase_order_document(
    purchase_order_id: uuid.UUID,
    data: GeneratePurchaseOrderDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    return await service.generate_purchase_order_document(db, organization_id, current_user.id, purchase_order_id, data)


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


# Centre administratif et opérationnel de la station — Sécurité
# (SecurityEquipment), Fournisseurs par station (StationSupplier), Finances.


@router.post("/security-equipment", response_model=SecurityEquipmentResponse, status_code=201)
async def create_security_equipment(
    data: CreateSecurityEquipmentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SecurityEquipmentResponse:
    return await service.create_security_equipment(db, organization_id, current_user.id, data)


@router.patch("/security-equipment/{security_equipment_id}", response_model=SecurityEquipmentResponse)
async def update_security_equipment(
    security_equipment_id: uuid.UUID,
    data: UpdateSecurityEquipmentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> SecurityEquipmentResponse:
    return await service.update_security_equipment(db, organization_id, current_user.id, security_equipment_id, data)


@router.get("/security-equipment", response_model=Page[SecurityEquipmentResponse])
async def list_security_equipment(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_security_equipment(db, organization_id, current_user.id, pagination, stationId)


@router.post("/station-suppliers", response_model=StationSupplierResponse, status_code=201)
async def create_station_supplier(
    data: CreateStationSupplierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationSupplierResponse:
    return await service.create_station_supplier(db, organization_id, current_user.id, data)


@router.patch("/station-suppliers/{station_supplier_id}", response_model=StationSupplierResponse)
async def update_station_supplier(
    station_supplier_id: uuid.UUID,
    data: UpdateStationSupplierRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationSupplierResponse:
    return await service.update_station_supplier(db, organization_id, current_user.id, station_supplier_id, data)


@router.get("/station-suppliers", response_model=Page[StationSupplierResponse])
async def list_station_suppliers(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_station_suppliers(db, organization_id, current_user.id, pagination, stationId)


@router.get(
    "/stations/{station_id}/financial",
    response_model=StationFinancialResponse,
    summary="Paramètres financiers d'une station",
    description="Retourne les paramètres financiers/comptables rattachés à la station (comptes, conditions de facturation...), distincts des données d'exploitation carburant.",
)
async def get_station_financial(
    station_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationFinancialResponse:
    return await service.get_station_financial(db, organization_id, current_user.id, station_id)


@router.patch(
    "/stations/{station_id}/financial",
    response_model=StationFinancialResponse,
    summary="Modifier les paramètres financiers d'une station",
    description="Met à jour partiellement les paramètres financiers d'une station.",
)
async def update_station_financial(
    station_id: uuid.UUID,
    data: UpdateStationFinancialRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationFinancialResponse:
    return await service.update_station_financial(db, organization_id, current_user.id, station_id, data)


@router.post("/station-staff", response_model=CreateStationStaffResponse, status_code=201)
async def create_station_staff_member(
    data: CreateStationStaffRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CreateStationStaffResponse:
    return await service.create_station_staff_member(db, organization_id, current_user.id, data)


@router.patch("/station-staff/{user_id}", response_model=StationStaffResponse)
async def update_station_staff_member(
    user_id: uuid.UUID,
    data: UpdateStationStaffRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationStaffResponse:
    return await service.update_station_staff_profile(db, organization_id, current_user.id, user_id, data)


@router.post("/station-staff/{user_id}/deactivate", response_model=StationStaffResponse)
async def deactivate_station_staff_member(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationStaffResponse:
    return await service.deactivate_station_staff_access(db, organization_id, current_user.id, user_id)


@router.put("/station-staff/{user_id}/role", response_model=StationStaffResponse)
async def change_station_staff_member_role(
    user_id: uuid.UUID,
    data: ChangeStationStaffRoleRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationStaffResponse:
    return await service.change_station_staff_role(db, organization_id, current_user.id, user_id, data)


@router.post("/station-staff/{user_id}/reset-password", response_model=ResetStationStaffPasswordResponse)
async def reset_station_staff_member_password(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ResetStationStaffPasswordResponse:
    temporary_password = await service.reset_station_staff_password(db, organization_id, current_user.id, user_id)
    return ResetStationStaffPasswordResponse(temporaryPassword=temporary_password)


@router.get("/station-staff", response_model=list[StationStaffResponse])
async def list_station_staff_members(
    stationId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[StationStaffResponse]:
    return await service.list_station_staff_profiles(db, organization_id, current_user.id, stationId)


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


@router.patch("/regulatory-documents/{document_id}", response_model=RegulatoryDocumentResponse)
async def update_regulatory_document(
    document_id: uuid.UUID,
    data: UpdateRegulatoryDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> RegulatoryDocumentResponse:
    return await service.update_regulatory_document(db, organization_id, current_user.id, document_id, data)


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


@router.get(
    "/stations/{station_id}/reconciliation-settings",
    response_model=StationReconciliationSettingsResponse | None,
    summary="Paramètres de réconciliation de stock d'une station",
    description="Retourne la dérogation de réconciliation configurée pour cette station (seuils de tolérance, etc.), ou `null` si la station utilise la configuration par défaut de l'organisation.",
)
async def get_station_reconciliation_settings(
    station_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationReconciliationSettingsResponse | None:
    return await service.get_station_reconciliation_settings(db, organization_id, current_user.id, station_id)


@router.put(
    "/stations/{station_id}/reconciliation-settings",
    response_model=StationReconciliationSettingsResponse,
    summary="Créer ou remplacer les paramètres de réconciliation d'une station",
    description="Crée ou remplace intégralement la dérogation de réconciliation de la station. Un seul enregistrement par station : cette configuration est un état courant, pas un historique — un appel répété écrase le précédent au lieu d'en empiler un nouveau.",
)
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


@router.post(
    "/tanks/{tank_id}/reconcile-stock",
    response_model=ReconciliationRecordResponse,
    summary="Réconcilier le stock d'une cuve pour une journée",
    description=(
        "Compare, pour la cuve et la journée donnée, le volume vendu déclaré (ventes enregistrées) "
        "au volume vendu déduit de la télémétrie (agrégat journalier de niveau de cuve), et produit "
        "un enregistrement de réconciliation avec l'écart constaté. Recalcule à chaque appel : "
        "rejouer cet endpoint pour le même jour est sans effet de bord destructif mais régénère "
        "l'enregistrement."
    ),
)
async def reconcile_stock(
    tank_id: uuid.UUID,
    day: date,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRecordResponse:
    return await service.evaluate_stock_reconciliation(db, organization_id, current_user.id, tank_id, day)
