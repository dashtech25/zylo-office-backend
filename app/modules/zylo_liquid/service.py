import logging
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.alerts import service as alerts_service
from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.files import service as files_service
from app.files.schemas import DocumentResponse
from app.core.security import hash_password
from app.identity.models import OrganizationUser, User
from app.identity.service import build_user, check_email_available
from app.rbac.models import UserRole
from app.rbac.service import assign_role, unassign_role
from app.shared.simple_cache import TTLCache
from app.shared.storage import get_storage_backend

# Cache TTL 60s pour les listes de produits carburant — quasi statique,
# refetché sans cache sur chaque requête sinon (Phase 1 audit, problème #3).
# Clé par organisation (`organizationId` : donnée scopée, jamais globale,
# voir commentaire de `FuelProduct.__table_args__`). Invalidé explicitement
# dans `create_fuel_product`/`update_fuel_product` ci-dessous — jamais de
# valeur périmée survivant une écriture dans le même process.
fuel_product_list_cache = TTLCache(default_ttl_seconds=60.0)
from app.modules.zylo_liquid.permissions import (
    CARRIER_MANAGE,
    CARRIER_READ,
    COMMERCIAL_ACCOUNT_MANAGE,
    COMMERCIAL_ACCOUNT_READ,
    DELIVERY_READ,
    LEAK_EVENT_READ,
    DECLARATION_LOCK,
    EQUIPMENT_MANAGE,
    EQUIPMENT_READ,
    INTERVENTION_ASSIGN,
    INTERVENTION_CLOSE,
    INTERVENTION_CREATE,
    INTERVENTION_READ,
    PRODUCT_SALE_CANCEL,
    PRODUCT_SALE_CREATE,
    PRODUCT_SALE_READ,
    REGULATORY_DECLARATION_MANAGE,
    REGULATORY_DECLARATION_READ,
    REGULATORY_DOCUMENT_ARCHIVE,
    REGULATORY_DOCUMENT_CREATE,
    REGULATORY_DOCUMENT_MANAGE,
    REGULATORY_DOCUMENT_READ,
    RECONCILIATION_READ,
    RECONCILIATION_SETTINGS_MANAGE,
    SELLABLE_PRODUCT_MANAGE,
    SELLABLE_PRODUCT_READ,
    TECHNICIAN_MANAGE,
    TECHNICIAN_READ,
    TRUCK_MANAGE,
    TRUCK_READ,
    TRUCK_ORDER_ASSIGNMENT_MANAGE,
    DELIVERY_DECLARATION_CREATE,
    DELIVERY_DECLARATION_READ,
    INCIDENT_DECLARATION_CREATE,
    INCIDENT_DECLARATION_READ,
    LEAK_TEST_DECLARATION_CREATE,
    LEAK_TEST_DECLARATION_READ,
    MANUAL_GAUGING_DECLARATION_CREATE,
    MANUAL_GAUGING_DECLARATION_READ,
    PAYMENT_CREATE,
    PAYMENT_READ,
    PRICE_HISTORY_CREATE,
    PRICE_HISTORY_READ,
    PURCHASE_ORDER_MANAGE,
    PURCHASE_ORDER_READ,
    QUALITY_CHECK_DECLARATION_CREATE,
    QUALITY_CHECK_DECLARATION_READ,
    RECEIVABLE_MANAGE,
    RECEIVABLE_READ,
    SALE_CREATE,
    SALE_READ,
    SHIFT_CASH_DECLARATION_CREATE,
    SHIFT_CASH_DECLARATION_READ,
    STATION_READ,
    SECURITY_EQUIPMENT_MANAGE,
    SECURITY_EQUIPMENT_READ,
    STATION_SUPPLIER_MANAGE,
    STATION_SUPPLIER_READ,
    STATION_FINANCIAL_MANAGE,
    STATION_FINANCIAL_READ,
    STATION_STAFF_MANAGE,
    STATION_STAFF_READ,
    STATION_SERVICE_MANAGE,
    STATION_SERVICE_READ,
    PRICING_POLICY_MANAGE,
    PRICING_POLICY_READ,
    STATION_FUEL_PRODUCT_MANAGE,
    STATION_FUEL_PRODUCT_READ,
    SUPPLIER_MANAGE,
    SUPPLIER_READ,
    TANK_READ,
    PUMP_READ,
)
from app.rbac.service import list_visible_resource_ids, user_has_permission
from app.modules.zylo_liquid.algorithms import (
    LEAK_THRESHOLD_LPH,
    RECONCILIATION_DELIVERY_STALE_PENDING_HOURS_DEFAULT,
    RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_FIXED_LITERS_DEFAULT,
    RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_PERCENT_DEFAULT,
    RECONCILIATION_DELIVERY_WINDOW_HOURS_DEFAULT,
    RECONCILIATION_GAUGING_HEIGHT_TOLERANCE_MM_DEFAULT,
    RECONCILIATION_QUALITY_CHECK_WINDOW_HOURS_DEFAULT,
    classify_tank_variation,
    compute_leak_rate_lph,
    compute_net_corrected_volume,
    correct_volume_to_reference_temperature,
    detect_deliveries,
    detect_delivery_in_progress,
    evaluate_threshold_alarms,
    interpolate_height_to_volume,
    is_leak_detected,
)
from app.modules.zylo_liquid.document_generation import generate_purchase_order_docx, generate_purchase_order_pdf
from app.modules.zylo_liquid.models import (
    Authorization,
    Carrier,
    CommercialAccount,
    DeclarationMixin,
    DeliveryDeclaration,
    DeliveryDeclarationLine,
    DeliveryDetected,
    Driver,
    Equipment,
    FuelProduct,
    TruckOrderAssignment,
    HolykellAccount,
    HolykellDeviceRegistry,
    IncidentDeclaration,
    Intervention,
    LeakageRecord,
    LeakTestDeclaration,
    ManualGaugingDeclaration,
    Payment,
    PriceHistory,
    Pump,
    SellableProductPrice,
    ProductSaleLine,
    ProductSaleTransaction,
    PurchaseOrder,
    PurchaseOrderLine,
    QualityCheckDeclaration,
    Receivable,
    ReconciliationRecord,
    RegulatoryDeclaration,
    RegulatoryDocument,
    Sale,
    SecurityEquipment,
    SellableProduct,
    StationReconciliationSettings,
    ShiftCashDeclaration,
    Station,
    StationFuelProduct,
    StationProductPricingPolicy,
    StationService,
    StationStaffProfile,
    StationSupplier,
    Supplier,
    Tank,
    TankCalibrationPoint,
    TankCashDailyAggregate,
    TankMeasurement,
    TankSensorMapping,
    Technician,
    Truck,
    Vehicle,
)
from app.modules.zylo_liquid.schemas import (
    AuthorizationResponse,
    CarrierResponse,
    CommercialAccountResponse,
    CreateAuthorizationRequest,
    CreateCarrierRequest,
    CreateCommercialAccountRequest,
    CorrectDeliveryDeclarationLinesRequest,
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
    CreatePriceHistoryRequest,
    CreatePumpRequest,
    UpdatePumpRequest,
    PumpResponse,
    CreatePurchaseOrderRequest,
    CreateQualityCheckDeclarationRequest,
    GeneratePurchaseOrderDocumentRequest,
    CreateSaleRequest,
    CreateShiftCashDeclarationRequest,
    CreateStationFuelProductRequest,
    CreateStationRequest,
    CreateSupplierRequest,
    CreateTankRequest,
    CreateTankSensorMappingRequest,
    CreateTruckRequest,
    CreateVehicleRequest,
    CurrencyCashBlock,
    DeliveryDeclarationLineResponse,
    DeliveryDeclarationResponse,
    DeliveryDetectedResponse,
    DeliveryReconciliationCandidateResponse,
    ManualReconcileDeliveryDeclarationLineRequest,
    DeliveryInProgressResponse,
    DriverResponse,
    HolykellSensorLiveState,
    IncidentDeclarationResponse,
    LeakEventResponse,
    LeakTestDeclarationResponse,
    ManualGaugingDeclarationResponse,
    NetworkCashSummaryResponse,
    NetworkProductCashLine,
    NetworkSummaryProductLine,
    NetworkSummaryResponse,
    PaymentResponse,
    PriceHistoryResponse,
    ProductCashLine,
    PurchaseOrderLineResponse,
    PurchaseOrderResponse,
    QualityCheckDeclarationResponse,
    ReceivableResponse,
    ReplaceTankCalibrationPointsRequest,
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
    UpdateStationFuelProductThresholdsRequest,
    StationFuelProductOverviewResponse,
    CreateStationServiceRequest,
    UpdateStationServiceRequest,
    StationServiceResponse,
    UpdatePricingPolicyRequest,
    PricingPolicyResponse,
    SaleResponse,
    ShiftCashDeclarationResponse,
    StationCashDetailResponse,
    StationCashSummaryLine,
    StationCurrentStateResponse,
    StationFuelProductResponse,
    StationResponse,
    SupplierResponse,
    TankCashResponse,
    TankCashSummaryLine,
    TankCurrentStateResponse,
    TankMeasurementResponse,
    TankResponse,
    TankSensorMappingResponse,
    TruckResponse,
    TruckOrderAssignmentRequest,
    TruckOrderAssignmentResponse,
    VehicleResponse,
    UpdateCarrierRequest,
    UpdateCommercialAccountRequest,
    UpdateDeliveryDeclarationRequest,
    UpdateFuelProductRequest,
    UpdateIncidentDeclarationRequest,
    UpdateLeakTestDeclarationRequest,
    UpdateManualGaugingDeclarationRequest,
    UpdateQualityCheckDeclarationRequest,
    UpdateShiftCashDeclarationRequest,
    UpdateStationFuelProductRequest,
    UpdatePriceHistoryRequest,
    UpdateStationRequest,
    UpdateSupplierRequest,
    UpdateTankRequest,
    UpdateTruckRequest,
    AssignInterventionRequest,
    BulkImportRowError,
    BulkImportSalesRequest,
    BulkImportSalesResponse,
    BulkImportSellableProductsRequest,
    BulkImportSellableProductsResponse,
    CloseInterventionRequest,
    CreateEquipmentRequest,
    CreateInterventionRequest,
    CreateProductSaleTransactionRequest,
    CreateRegulatoryDeclarationRequest,
    CreateRegulatoryDocumentRequest,
    CreateSellableProductPriceRequest,
    CreateSellableProductRequest,
    CreateTechnicianRequest,
    EquipmentResponse,
    InterventionResponse,
    ProductSaleLineResponse,
    ProductSaleTransactionResponse,
    RegulatoryDeclarationResponse,
    RegulatoryDocumentResponse,
    SellableProductPriceResponse,
    SellableProductResponse,
    TechnicianResponse,
    UpdateEquipmentRequest,
    UpdateRegulatoryDocumentRequest,
    UpdateSellableProductPriceRequest,
    UpdateSellableProductRequest,
)
from app.shared.currency import Currency
from app.shared.geo import City, Country, Region
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalise un datetime potentiellement "aware" (ex. suffixe Z, ISO
    8601 UTC standard envoyé par le frontend via `Date.toISOString()`) vers
    naïf en UTC — convention déjà établie dans ce module (comparaisons
    toujours en naïf UTC). Sans cette normalisation, comparer directement à
    une colonne naïve lève `TypeError: can't subtract offset-naive and
    offset-aware datetimes` côté asyncpg dès qu'un client envoie un
    datetime avec fuseau explicite — bug réel déjà rencontré et corrigé au
    cas par cas (création de prix, snapshot réseau) ; factorisé ici pour
    être appliqué systématiquement à tout filtre from_date/to_date reçu
    d'une requête HTTP, plutôt que de laisser chaque endpoint réinventer la
    même normalisation ou l'oublier."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


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


async def update_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID, data: UpdateFuelProductRequest
) -> FuelProduct:
    fuel_product = await get_fuel_product(db, organization_id, fuel_product_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fuel_product, field, value)
    await db.commit()
    await db.refresh(fuel_product)
    fuel_product_list_cache.invalidate_prefix(f"org:{organization_id}:")
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


# ================================================================
# Page Exploitation (Centre administratif de la station) — vue d'ensemble
# carburants (seuils + stock agrégé + prix courant), catalogue de services,
# politique commerciale par produit.
# ================================================================


async def update_station_fuel_product_thresholds(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, association_id: uuid.UUID, data: UpdateStationFuelProductThresholdsRequest
) -> StationFuelProductResponse:
    result = await db.execute(
        select(StationFuelProduct, Station)
        .join(Station, Station.id == StationFuelProduct.stationId)
        .where(StationFuelProduct.id == association_id, Station.organizationId == organization_id)
    )
    row = result.one_or_none()
    if row is None:
        raise AppError(code="station_fuel_product_not_found", message="Association station/produit introuvable.", status_code=404)
    association, station = row
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_FUEL_PRODUCT_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(association, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationFuelProduct.update", entity_type="StationFuelProduct", entity_id=association.id,
        summary="Modification des seuils de réassort", scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(association)
    return StationFuelProductResponse.model_validate(association)


def _compute_stock_status(current_liters: float | None, min_threshold: float | None, critical_threshold: float | None) -> str:
    """Jamais un statut inventé quand aucun seuil n'est défini — 'inconnu'
    explicite plutôt qu'un 'normal' par défaut trompeur."""
    if current_liters is None or (min_threshold is None and critical_threshold is None):
        return "inconnu"
    if critical_threshold is not None and current_liters <= critical_threshold:
        return "critique"
    if min_threshold is not None and current_liters <= min_threshold:
        return "attention"
    return "normal"


async def list_station_fuel_products_overview(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> list[StationFuelProductOverviewResponse]:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_FUEL_PRODUCT_READ)

    result = await db.execute(
        select(StationFuelProduct, FuelProduct)
        .join(FuelProduct, FuelProduct.id == StationFuelProduct.fuelProductId)
        .where(StationFuelProduct.stationId == station_id)
        .order_by(FuelProduct.name)
    )
    associations = result.all()

    tanks_result = await db.execute(select(Tank).where(Tank.stationId == station_id, Tank.active.is_(True)))
    tanks_by_product: dict[uuid.UUID, list[Tank]] = {}
    for tank in tanks_result.scalars().all():
        tanks_by_product.setdefault(tank.fuelProductId, []).append(tank)

    rows: list[StationFuelProductOverviewResponse] = []
    for association, fuel_product in associations:
        tanks = tanks_by_product.get(fuel_product.id, [])
        capacity_liters = sum(float(t.calibratedCapacityLiters or t.capacityLiters) for t in tanks)
        current_volume: float | None = None
        if tanks:
            states = [await get_tank_current_state(db, t) for t in tanks]
            volumes = [s.volumeLiters for s in states if s.volumeLiters is not None]
            current_volume = sum(volumes) if volumes else None

        price_result = await db.execute(
            select(PriceHistory, Currency.code)
            .join(Currency, Currency.id == PriceHistory.currencyId)
            .where(
                PriceHistory.fuelProductId == fuel_product.id,
                PriceHistory.stationId == station_id,
                PriceHistory.effectiveFrom <= datetime.now(timezone.utc).replace(tzinfo=None),
            )
            .order_by(PriceHistory.effectiveFrom.desc())
            .limit(1)
        )
        price_row = price_result.first()
        current_price, currency_code, price_effective_from = (
            (float(price_row[0].priceAmount), price_row[1], price_row[0].effectiveFrom) if price_row else (None, None, None)
        )

        rows.append(StationFuelProductOverviewResponse(
            id=association.id, stationId=station_id, fuelProductId=fuel_product.id,
            fuelProductName=fuel_product.name, fuelProductCode=fuel_product.code, displayColor=fuel_product.displayColor,
            active=association.active,
            minThresholdLiters=association.minThresholdLiters, criticalThresholdLiters=association.criticalThresholdLiters,
            safetyStockLiters=association.safetyStockLiters,
            capacityLiters=capacity_liters, currentVolumeLiters=current_volume,
            status=_compute_stock_status(current_volume, association.minThresholdLiters, association.criticalThresholdLiters),
            currentPriceAmount=current_price, currencyCode=currency_code, priceEffectiveFrom=price_effective_from,
        ))
    return rows


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


async def _resolve_applicable_price(
    db: AsyncSession, station_id: uuid.UUID, fuel_product_id: uuid.UUID, at
) -> tuple[PriceHistory | None, str | None]:
    """Prix applicable à un instant donné (Point 2 §7.6, niveau_1_...md
    §16) : la ligne `PriceHistory` propre à la station dont `effectiveFrom`
    est la plus récente antérieure ou égale à l'instant demandé — jamais un
    prix postérieur, jamais le prix courant en cache. À défaut, repli sur le
    prix par défaut du réseau (`stationId IS NULL`, audit Configuration
    carburant P2 §E) — jamais l'inverse (un prix propre à la station prime
    toujours sur le défaut réseau, même plus ancien).

    Retourne `(price, reason)` : `reason` n'est renseigné que si `price` est
    `None`, pour distinguer "aucun prix réseau du tout pour ce produit"
    (`no_applicable_price`) de "un prix réseau par défaut existe mais dans
    une devise différente de celle résolue pour la station"
    (`price_currency_mismatch`) — un cas de configuration incohérente
    silencieusement confondu avec une absence totale de prix avant ce
    correctif (P0-7, audit module Stations 2026-09-16)."""
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.stationId == station_id, PriceHistory.fuelProductId == fuel_product_id, PriceHistory.effectiveFrom <= at)
        .order_by(PriceHistory.effectiveFrom.desc())
        .limit(1)
    )
    price = result.scalar_one_or_none()
    if price is not None:
        return price, None

    default_conditions = [
        PriceHistory.stationId.is_(None),
        PriceHistory.fuelProductId == fuel_product_id,
        PriceHistory.effectiveFrom <= at,
    ]
    # Plusieurs prix réseau peuvent désormais coexister dans des devises
    # différentes (refonte multi-devise, Phase 4 §1 de
    # refonte-configuration-zylo-liquid.md) : filtrer par la devise de la
    # station pour ne jamais retourner un prix dans la mauvaise devise.
    # Repli sur "toutes devises" seulement si la devise de la station n'est
    # pas résolvable (chaîne géo incomplète) — jamais casser un affichage
    # déjà fonctionnel pour cette raison.
    station = await db.get(Station, station_id)
    station_currency = None
    if station is not None:
        try:
            station_currency = await _resolve_station_default_currency(db, station)
            default_conditions.append(PriceHistory.currencyId == station_currency.id)
        except AppError:
            pass

    default_result = await db.execute(
        select(PriceHistory).where(*default_conditions).order_by(PriceHistory.effectiveFrom.desc()).limit(1)
    )
    default_price = default_result.scalar_one_or_none()
    if default_price is not None:
        return default_price, None

    if station_currency is not None:
        any_currency_result = await db.execute(
            select(PriceHistory.id)
            .where(PriceHistory.stationId.is_(None), PriceHistory.fuelProductId == fuel_product_id, PriceHistory.effectiveFrom <= at)
            .limit(1)
        )
        if any_currency_result.scalar_one_or_none() is not None:
            return None, "price_currency_mismatch"

    return None, "no_applicable_price"


async def _resolve_tank_monetary_value(
    db: AsyncSession, tank: Tank, volume_liters: float | None, at
) -> tuple[float | None, str | None, str | None, float | None]:
    """Retourne (valeur, code devise, motif de non-calcul, prix unitaire au
    litre) — jamais un zéro quand le prix n'est pas connu (Point 2 §7.6).
    Le prix unitaire est renvoyé même quand `volume_liters` est `None`, pour
    permettre à un appelant (ex. carte financière de la cuve) d'afficher le
    prix courant du produit indépendamment du calcul de valeur du stock —
    remplace `FuelProduct.currentPriceFcfa`, jamais mis à jour (retiré du
    modèle, audit Configuration carburant §B/§P1)."""
    price, price_reason = await _resolve_applicable_price(db, tank.stationId, tank.fuelProductId, at)
    if price is None:
        return None, None, price_reason, None
    currency = await db.get(Currency, price.currencyId)
    currency_code = currency.code if currency else None
    unit_price = float(price.priceAmount)
    if volume_liters is None:
        return None, currency_code, "volume_not_calculable", unit_price
    return volume_liters * unit_price, currency_code, None, unit_price


def _build_tank_current_state(
    tank: Tank,
    product_level: HolykellDeviceRegistry | None,
    water_registry: HolykellDeviceRegistry | None,
    temperature_registry: HolykellDeviceRegistry | None,
    calibration_points: list[tuple[float, float]],
    fuel_product: FuelProduct | None,
    price: PriceHistory | None,
    currency_code: str | None,
    price_reason: str | None = None,
) -> TankCurrentStateResponse:
    """Calcul pur (aucun accès DB) de l'état d'une cuve à partir de données
    déjà chargées — factorisé hors de `get_tanks_current_state_batch` pour
    que le calcul reste écrit une seule fois, jamais réimplémenté entre la
    version batchée et un éventuel besoin ponctuel sur une seule cuve
    (audit performance 2026-09-11)."""
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
            sellableVolumeLiters=None,
            monetaryValue=None,
            currencyCode=None,
            monetaryValueNotCalculableReason="volume_not_calculable",
            unitPriceAmount=None,
            waterHeightMm=None,
            waterVolumeLiters=None,
            temperatureC=None,
            emptyVolumeLiters=None,
            lastMeasurementAt=None,
        )

    sensor_status = "online" if product_level.hkLastStatus == 1 else "offline"
    height_mm = float(product_level.lastValue)

    volume_brut = interpolate_height_to_volume(calibration_points, height_mm) if calibration_points else None
    volume_not_calculable_reason = None if volume_brut is not None else "no_calibration_table"

    water_height_mm = float(water_registry.lastValue) if water_registry and water_registry.lastValue is not None else None
    water_volume = (
        interpolate_height_to_volume(calibration_points, water_height_mm)
        if water_height_mm is not None and calibration_points
        else (0.0 if water_height_mm is None else None)
    )

    # product_level et water_level sont deux capteurs indépendants, chacun
    # interpolé sur la même table de calibration : près du vide, le bruit de
    # mesure peut faire remonter le niveau d'eau légèrement au-dessus du
    # niveau produit, donnant un brut-eau négatif qui n'a pas de sens
    # physique (l'eau ne peut pas dépasser le volume total mesuré) — d'où le
    # plancher à 0 plutôt qu'un volume net négatif affiché tel quel.
    volume_net = max(0.0, volume_brut - water_volume) if (volume_brut is not None and water_volume is not None) else None
    empty_volume = (float(tank.capacityLiters) - volume_brut) if volume_brut is not None else None

    # Volume vendable = volume réel (net, température actuelle) moins le
    # volume correspondant au seuil bas (Tank.lowAlarmMm) — hauteur en
    # dessous de laquelle on ne vend plus (crépine d'aspiration, fond de
    # cuve non exploitable). Jamais négatif : sous le seuil bas, il n'y a
    # simplement rien de vendable, pas un chiffre négatif.
    volume_at_low_alarm = interpolate_height_to_volume(calibration_points, float(tank.lowAlarmMm)) if calibration_points else None
    sellable_volume = max(0.0, volume_net - volume_at_low_alarm) if (volume_net is not None and volume_at_low_alarm is not None) else None

    temperature_c = (
        float(temperature_registry.lastValue) if temperature_registry and temperature_registry.lastValue is not None else None
    )

    volume_15c = None
    if volume_net is not None and temperature_c is not None and fuel_product is not None and fuel_product.thermalExpansionCoefficient is not None:
        volume_15c = correct_volume_to_reference_temperature(volume_net, temperature_c, float(fuel_product.thermalExpansionCoefficient))

    if price is None:
        monetary_value, monetary_reason, unit_price = None, (price_reason or "no_applicable_price"), None
    else:
        unit_price = float(price.priceAmount)
        if volume_net is None:
            monetary_value, monetary_reason = None, "volume_not_calculable"
        else:
            monetary_value, monetary_reason = volume_net * unit_price, None

    return TankCurrentStateResponse(
        tankId=tank.id,
        tankNumber=tank.tankNumber,
        displayName=tank.displayName,
        sensorStatus=sensor_status,
        heightMm=height_mm,
        volumeLiters=volume_net,
        volumeNotCalculableReason=volume_not_calculable_reason,
        volumeLiters15C=volume_15c,
        sellableVolumeLiters=sellable_volume,
        monetaryValue=monetary_value,
        currencyCode=currency_code if price is not None else None,
        monetaryValueNotCalculableReason=monetary_reason,
        unitPriceAmount=unit_price,
        waterHeightMm=water_height_mm,
        waterVolumeLiters=water_volume,
        temperatureC=temperature_c,
        emptyVolumeLiters=empty_volume,
        lastMeasurementAt=product_level.lastValueAt,
    )


async def get_tanks_current_state_batch(db: AsyncSession, tanks: list[Tank]) -> dict[uuid.UUID, TankCurrentStateResponse]:
    """Version batchée de l'ancien `get_tank_current_state` (audit
    performance 2026-09-11) : un aller-retour DB par TYPE de donnée pour
    l'ensemble des cuves demandées (capteurs, calibrations, produits, prix,
    devises), au lieu d'un aller-retour par cuve — jusqu'à 8 requêtes
    séquentielles par cuve auparavant (`network/summary` mesuré à 27s pour
    13 cuves). Mêmes résultats cuve par cuve, calcul inchangé
    (`_build_tank_current_state`). À utiliser partout où plusieurs cuves
    sont traitées ensemble (résumé réseau, état d'une station) ; pour un
    besoin ponctuel sur une seule cuve, appeler avec une liste à un élément."""
    if not tanks:
        return {}

    tank_ids = [t.id for t in tanks]

    registry_result = await db.execute(
        select(TankSensorMapping.tankId, TankSensorMapping.measurementType, HolykellDeviceRegistry)
        .join(HolykellDeviceRegistry, HolykellDeviceRegistry.hkSensorId == TankSensorMapping.hkSensorId)
        .where(TankSensorMapping.tankId.in_(tank_ids), TankSensorMapping.active.is_(True))
    )
    registry_by_key: dict[tuple[uuid.UUID, str], HolykellDeviceRegistry] = {}
    for tank_id, measurement_type, registry in registry_result.all():
        registry_by_key[(tank_id, measurement_type)] = registry

    calibration_result = await db.execute(
        select(TankCalibrationPoint.tankId, TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(
            TankCalibrationPoint.tankId.in_(tank_ids)
        )
    )
    calibration_by_tank: dict[uuid.UUID, list[tuple[float, float]]] = {}
    for tank_id, height_mm, volume_liters in calibration_result.all():
        calibration_by_tank.setdefault(tank_id, []).append((float(height_mm), float(volume_liters)))

    fuel_product_ids = {t.fuelProductId for t in tanks}
    fuel_product_result = await db.execute(select(FuelProduct).where(FuelProduct.id.in_(fuel_product_ids)))
    fuel_product_by_id = {fp.id: fp for fp in fuel_product_result.scalars().all()}

    station_ids = {t.stationId for t in tanks}
    stations_result = await db.execute(select(Station).where(Station.id.in_(station_ids)))
    stations_by_id = {s.id: s for s in stations_result.scalars().all()}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pairs = {(t.stationId, t.fuelProductId) for t in tanks}
    price_by_pair = await _resolve_applicable_prices_batch(db, pairs, stations_by_id, now)

    currency_ids = {price.currencyId for price, _ in price_by_pair.values() if price is not None}
    currency_by_id: dict[uuid.UUID, Currency] = {}
    if currency_ids:
        currency_result = await db.execute(select(Currency).where(Currency.id.in_(currency_ids)))
        currency_by_id = {c.id: c for c in currency_result.scalars().all()}

    states: dict[uuid.UUID, TankCurrentStateResponse] = {}
    for tank in tanks:
        price, price_reason = price_by_pair.get((tank.stationId, tank.fuelProductId), (None, "no_applicable_price"))
        currency = currency_by_id.get(price.currencyId) if price is not None else None
        states[tank.id] = _build_tank_current_state(
            tank,
            registry_by_key.get((tank.id, "product_level")),
            registry_by_key.get((tank.id, "water_level")),
            registry_by_key.get((tank.id, "temperature")),
            calibration_by_tank.get(tank.id, []),
            fuel_product_by_id.get(tank.fuelProductId),
            price,
            currency.code if currency is not None else None,
            price_reason,
        )
    return states


async def get_tank_current_state(db: AsyncSession, tank: Tank) -> TankCurrentStateResponse:
    """Ponctuel, une seule cuve — délègue à la version batchée pour ne
    jamais réimplémenter le calcul (audit performance 2026-09-11). Pour
    plusieurs cuves à la fois, appeler directement
    `get_tanks_current_state_batch` (un seul aller-retour DB par type de
    donnée au lieu d'un par cuve)."""
    return (await get_tanks_current_state_batch(db, [tank]))[tank.id]


async def get_tank_current_state_by_id(db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> TankCurrentStateResponse:
    tank = await get_tank(db, organization_id, tank_id)
    return await get_tank_current_state(db, tank)


async def get_station_current_state(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> StationCurrentStateResponse:
    await get_station(db, organization_id, station_id)  # lève station_not_found si hors périmètre
    result = await db.execute(
        select(Tank).where(Tank.stationId == station_id, Tank.active.is_(True)).order_by(Tank.tankNumber)
    )
    tanks = result.scalars().all()
    states_by_id = await get_tanks_current_state_batch(db, tanks)
    states = [states_by_id[tank.id] for tank in tanks]
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
    from_date = _to_naive_utc(from_date)
    to_date = _to_naive_utc(to_date)
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
    tank_states = await get_tanks_current_state_batch(db, tanks)
    for tank in tanks:
        state = tank_states[tank.id]
        if state.volumeLiters is None:
            continue  # cuve sans mesure calculable exclue du total (jamais un zéro, Point 2 §3.2)

        entry = _init_product_entry(per_product, tank.fuelProductId)
        entry["stations"].add(tank.stationId)
        entry["tanks"] += 1
        entry["volume"] += state.volumeLiters
        # Volume vendable (cartes stock, audit validé) : toujours calculable
        # dès que `volumeLiters` l'est (même table de calibration pour le
        # seuil bas) — jamais gaté par la disponibilité du prix, contrairement
        # à sa valeur monétaire juste en dessous.
        entry["sellableVolume"] += state.sellableVolumeLiters or 0.0
        all_stations_with_data.add(tank.stationId)
        sellable_monetary = (
            state.sellableVolumeLiters * state.unitPriceAmount
            if state.sellableVolumeLiters is not None and state.unitPriceAmount is not None
            else None
        )
        _accumulate_monetary(entry, state.monetaryValue, sellable_monetary, state.currencyCode)

    products = _build_product_lines(per_product, fuel_products_by_id)

    return NetworkSummaryResponse(
        products=products,
        totalVolumeLiters=sum(p.totalVolumeLiters for p in products),
        totalStationCount=len(all_stations_with_data),
        totalTankCount=sum(p.tankCount for p in products),
        totalSellableVolumeLiters=sum(p.totalSellableVolumeLiters for p in products),
    )


def _init_product_entry(per_product: dict, fuel_product_id: uuid.UUID) -> dict:
    return per_product.setdefault(
        fuel_product_id,
        {"stations": set(), "tanks": 0, "volume": 0.0, "sellableVolume": 0.0, "monetary": 0.0, "sellableMonetary": 0.0, "currencies": set(), "incomplete_pricing": False},
    )


def _accumulate_monetary(entry: dict, monetary_value: float | None, sellable_monetary_value: float | None, currency_code: str | None) -> None:
    if monetary_value is None:
        entry["incomplete_pricing"] = True
        return
    entry["monetary"] += monetary_value
    entry["sellableMonetary"] += sellable_monetary_value or 0.0
    if currency_code is not None:
        entry["currencies"].add(currency_code)


def _build_product_lines(per_product: dict, fuel_products_by_id: dict) -> list[NetworkSummaryProductLine]:
    """Total monétaire par produit calculé uniquement si toutes les cuves
    de ce produit ont un prix applicable dans une seule et même devise —
    sinon la réponse l'indique explicitement, jamais une somme erronée
    entre devises différentes ou une valeur partielle silencieuse
    (Point 2 §7.6, niveau_1_...md §20). La valeur monétaire du volume
    vendable partage exactement la même porte (même prix/devise résolus par
    cuve) — jamais une deuxième résolution de prix, jamais une raison de
    non-calcul distincte."""
    lines = []
    for fuel_product_id, entry in per_product.items():
        if entry["incomplete_pricing"]:
            monetary_value, sellable_monetary_value, currency_code, reason = None, None, None, "incomplete_pricing"
        elif len(entry["currencies"]) > 1:
            monetary_value, sellable_monetary_value, currency_code, reason = None, None, None, "mixed_currencies"
        elif len(entry["currencies"]) == 1:
            monetary_value, sellable_monetary_value, currency_code, reason = entry["monetary"], entry["sellableMonetary"], next(iter(entry["currencies"])), None
        else:
            monetary_value, sellable_monetary_value, currency_code, reason = None, None, None, "no_applicable_price"

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
                totalSellableVolumeLiters=entry["sellableVolume"],
                totalSellableMonetaryValue=sellable_monetary_value,
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

        # Retour de rapprochement automatique (mission « flux de livraison
        # station », point 3 : « dès qu'une livraison est détectée ») —
        # best-effort, une détection reste valide même si ce retour échoue.
        try:
            tank = await db.get(Tank, tank_id)
            if tank is not None:
                for delivery in created:
                    await _reverse_match_delivery_detected(db, delivery, tank)
                await _sweep_stale_pending_delivery_declarations(db, tank.stationId)
        except Exception:
            await db.rollback()

    return created


async def get_delivery_in_progress_for_tank(db: AsyncSession, tank_id: uuid.UUID, lookback_minutes: int = 180) -> dict | None:
    """Version "en cours" de `run_delivery_detection_for_tank` : ne regarde
    qu'une fenêtre récente (pas tout l'historique — inutile et coûteux pour
    une hausse en cours) et ne persiste jamais rien. Retourne le dict brut
    de `detect_delivery_in_progress` avec les volumes déjà interpolés, ou
    None si aucune hausse n'est en cours sur la fenêtre."""
    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == "product_level", TankSensorMapping.active
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]
    if not sensor_ids:
        return None

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=lookback_minutes)
    measurements_result = await db.execute(
        select(TankMeasurement.measuredAt, TankMeasurement.rawValue)
        .where(TankMeasurement.hkSensorId.in_(sensor_ids), TankMeasurement.measuredAt >= since)
        .order_by(TankMeasurement.measuredAt)
    )
    measurements = [(measuredAt, float(rawValue)) for measuredAt, rawValue in measurements_result.all()]
    candidate = detect_delivery_in_progress(measurements)
    if candidate is None:
        return None

    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank_id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]
    start_volume = interpolate_height_to_volume(calibration_points, candidate["startHeightMm"]) if calibration_points else None
    current_volume = interpolate_height_to_volume(calibration_points, candidate["currentHeightMm"]) if calibration_points else None

    return {**candidate, "startVolumeLiters": start_volume, "currentVolumeLiters": current_volume}


async def list_deliveries_in_progress(db: AsyncSession, organization_id: uuid.UUID) -> list[DeliveryInProgressResponse]:
    """Balaie toutes les cuves actives de l'organisation — coût raisonnable
    à l'échelle d'un réseau de stations (dizaines de cuves), chaque
    recherche étant bornée à `lookback_minutes` plutôt qu'à tout
    l'historique. Jamais une deuxième source de vérité : une cuve dont la
    hausse vient de se stabiliser disparaîtra d'ici (elle devient une vraie
    `DeliveryDetected` au prochain cycle de `run_delivery_detection_for_tank`)."""
    tanks_result = await db.execute(
        select(Tank).join(Station, Station.id == Tank.stationId).where(Station.organizationId == organization_id, Tank.active)
    )
    tanks = list(tanks_result.scalars().all())

    results: list[DeliveryInProgressResponse] = []
    for tank in tanks:
        candidate = await get_delivery_in_progress_for_tank(db, tank.id)
        if candidate is None:
            continue
        results.append(
            DeliveryInProgressResponse(
                tankId=tank.id,
                stationId=tank.stationId,
                startTime=candidate["startTime"],
                startHeightMm=candidate["startHeightMm"],
                startVolumeLiters=candidate["startVolumeLiters"],
                currentTime=candidate["currentTime"],
                currentHeightMm=candidate["currentHeightMm"],
                currentVolumeLiters=candidate["currentVolumeLiters"],
            )
        )
    return results


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
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    from_date,
    to_date,
) -> Page:
    """Corrigé — même constat que `list_alerts`/`list_stations` : filtrage
    par portée réelle de l'utilisateur, pas seulement par organisation."""
    from_date = _to_naive_utc(from_date)
    to_date = _to_naive_utc(to_date)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, DELIVERY_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {DELIVERY_READ}.", status_code=403)

    stmt = (
        select(DeliveryDetected, Tank)
        .join(Tank, Tank.id == DeliveryDetected.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if not sees_all:
        stmt = stmt.where(Tank.stationId.in_(visible_station_ids))
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
            db, tank_id, "leak", triggered_at=end_time, triggered_value=leak_rate, threshold_value=LEAK_THRESHOLD_LPH
        )
    else:
        # D2 (refonte alertes) : un test de fuite négatif EST la vérité
        # mesurée qui referme l'alerte — jamais un clic humain qui
        # déclarerait la fuite réglée sans nouveau test.
        await alerts_service.auto_resolve_alert(
            db, station_id=tank.stationId, tank_id=tank_id, product_id=None,
            alert_type="leak", resolved_at=end_time,
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
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    result_filter: str | None,
    from_date,
    to_date,
) -> Page:
    """Corrigé — même constat que `list_alerts`/`list_deliveries`."""
    from_date = _to_naive_utc(from_date)
    to_date = _to_naive_utc(to_date)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, LEAK_EVENT_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {LEAK_EVENT_READ}.", status_code=403)

    stmt = (
        select(LeakageRecord, Tank)
        .join(Tank, Tank.id == LeakageRecord.tankId)
        .join(Station, Station.id == Tank.stationId)
        .where(Station.organizationId == organization_id)
    )
    if not sees_all:
        stmt = stmt.where(Tank.stationId.in_(visible_station_ids))
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


# SEVERITY_BY_ALERT_TYPE / AUTO_VERIFIABLE_ALERT_TYPES / _find_open_alert /
# _upsert_active_alert — déplacés vers `app/alerts/service.py` (2026-09-15,
# Phase 3 de la migration monolithe modulaire, renommée `upsert_active_alert`
# — voir la docstring de ce fichier). Les fonctions productrices d'alertes
# restées ici appellent désormais `alerts_service.upsert_active_alert`.


async def _create_alert_if_not_already_active(
    db: AsyncSession, tank_id: uuid.UUID, alert_type: str, triggered_at, triggered_value: float | None, threshold_value: float | None
) -> "Alert | None":
    """Compat : dérive `stationId` depuis la cuve, conserve tous les appels
    existants inchangés (seuils, fuite, livraison). Voir
    `app.alerts.service.upsert_active_alert` (D4) pour la version complète —
    types sans cuve, source polymorphe. Type de retour en chaîne (jamais
    importé) : ce module n'accède à Alerts que via `alerts_service`, jamais
    via `app.alerts.models` (contrat import-linter)."""
    tank = (await db.execute(select(Tank).where(Tank.id == tank_id))).scalar_one()
    return await alerts_service.upsert_active_alert(
        db, station_id=tank.stationId, tank_id=tank_id, alert_type=alert_type,
        triggered_at=triggered_at, triggered_value=triggered_value, threshold_value=threshold_value,
    )


# _auto_resolve_alert — déplacée vers `app/alerts/service.py` (2026-09-15,
# Phase 3), renommée `auto_resolve_alert`. Les appels ci-dessous utilisent
# désormais `alerts_service.auto_resolve_alert`.


async def run_alert_evaluation_for_tank(db: AsyncSession, tank_id: uuid.UUID) -> "list[Alert]":
    """Évalue l'état instantané d'une cuve (mêmes sources que l'endpoint 7 :
    `HolykellDeviceRegistry.lastValue`/`hkLastStatus`, jamais `TankMeasurement`)
    contre les 4 seuils déjà saisis sur `Tank` (endpoint 3) — algorithme de
    Point 13 §13.4, jamais réimplémenté. Sonde déconnectée détectée via
    `hkLastStatus` déjà maintenu par la synchronisation Holykell, jamais un
    seuil d'ancienneté inventé (même principe que l'endpoint 7, issue #35).

    D2 (refonte alertes) : chaque cycle referme aussi automatiquement toute
    alerte de ce type qui n'a plus lieu d'être — la mesure qui a créé
    l'alerte est la même qui la referme, jamais un clic humain non vérifié."""
    tank_result = await db.execute(select(Tank).where(Tank.id == tank_id))
    tank = tank_result.scalar_one()

    product_registry = await _get_active_registry_entry(db, tank_id, "product_level")
    created: "list[Alert]" = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if product_registry is None or product_registry.lastValue is None:
        return created

    if product_registry.hkLastStatus == 0:
        alert = await _create_alert_if_not_already_active(db, tank_id, "sensor_offline", now, None, None)
        if alert:
            created.append(alert)
        await db.commit()
        return created  # sonde déconnectée : aucune mesure fiable, pas de comparaison de seuils

    # La sonde répond de nouveau : toute alerte "sensor_offline" ouverte sur
    # cette cuve n'a plus de raison d'être.
    await alerts_service.auto_resolve_alert(db, station_id=tank.stationId, tank_id=tank_id, product_id=None, alert_type="sensor_offline", resolved_at=now)

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

    for alert_type in threshold_by_type:
        if alert_type in triggered_types:
            alert = await _create_alert_if_not_already_active(
                db, tank_id, alert_type, now, value_by_type[alert_type], threshold_by_type[alert_type]
            )
            if alert:
                created.append(alert)
        else:
            # Condition disparue depuis le dernier cycle (D2).
            await alerts_service.auto_resolve_alert(db, station_id=tank.stationId, tank_id=tank_id, product_id=None, alert_type=alert_type, resolved_at=now)

    await db.commit()
    return created


# _alert_to_response / list_alerts / _get_alert_and_tank / get_alert /
# acknowledge_alert / resolve_alert — déplacées vers `app/alerts/service.py`
# et `app/alerts/router.py` (2026-09-15, Phase 3 de la migration monolithe
# modulaire). Les producteurs d'alertes restés ici (ci-dessous) appellent
# désormais `alerts_service.upsert_active_alert`/`auto_resolve_alert`.


# D5 (refonte alertes, incrémentation détection réelle) — 3 états système
# qui empêchent Zylo Liquid de fonctionner ou d'afficher une information
# fiable (Étape 1 §7 de la mission : « si le système a besoin d'une donnée
# pour calculer/afficher une information et qu'elle manque, c'est un état
# système important »). Structurel — ne dépend d'aucune mesure télémétrique,
# donc jamais évalué par `run_alert_evaluation_for_tank` (qui ne tourne que
# quand une mesure arrive) : balayé périodiquement, voir
# `evaluate_structural_alerts_for_organization` et
# `app/modules/zylo_liquid/telemetry_sync.py::structural_sweep_loop`.

async def evaluate_price_missing_alert(db: AsyncSession, station_id: uuid.UUID, fuel_product_id: uuid.UUID) -> None:
    """Un produit vendu à une station (`StationFuelProduct.active`) sans
    prix résolu (`_resolve_applicable_price`, ni prix station ni défaut
    réseau) empêche tout calcul fiable de valeur de stock/vente — jamais un
    champ de réponse dégradée silencieux (constat Étape 1 : c'était le cas
    avant cette incrémentation, `monetaryValueNotCalculableReason`)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    price, _ = await _resolve_applicable_price(db, station_id, fuel_product_id, now)
    if price is None:
        await alerts_service.upsert_active_alert(
            db, station_id=station_id, product_id=fuel_product_id, alert_type="price_missing",
            triggered_at=now, source_type="fuelProduct", source_id=fuel_product_id,
        )
    else:
        await alerts_service.auto_resolve_alert(
            db, station_id=station_id, tank_id=None, product_id=fuel_product_id,
            alert_type="price_missing", resolved_at=now,
        )


async def evaluate_sensor_mapping_missing_alert(db: AsyncSession, tank: Tank) -> None:
    """Une cuve pilotée par console (`dataSourceType='console'`) sans
    mapping capteur actif de type `product_level` ne peut jamais recevoir de
    mesure — la cuve reste invisible à toute évaluation d'alerte de seuil
    tant que ce mapping manque. Les cuves `dataSourceType='direct'` (saisie
    manuelle assumée, jamais de capteur attendu) sont hors périmètre de ce
    type — jamais une fausse alerte sur une cuve volontairement sans sonde."""
    if tank.dataSourceType != "console":
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    mapping = (await db.execute(
        select(TankSensorMapping).where(
            TankSensorMapping.tankId == tank.id,
            TankSensorMapping.measurementType == "product_level",
            TankSensorMapping.active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if mapping is None:
        await alerts_service.upsert_active_alert(
            db, station_id=tank.stationId, tank_id=tank.id, alert_type="sensor_mapping_missing", triggered_at=now,
        )
    else:
        await alerts_service.auto_resolve_alert(
            db, station_id=tank.stationId, tank_id=tank.id, product_id=None,
            alert_type="sensor_mapping_missing", resolved_at=now,
        )


async def evaluate_calibration_missing_alert(db: AsyncSession, tank: Tank) -> None:
    """Sans aucun point de calibration, la conversion hauteur mesurée →
    volume (`interpolate_height_to_volume`, algorithms.py) est impossible —
    toute mesure télémétrique de cette cuve reste inexploitable tant que ce
    barème n'existe pas."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count_result = await db.execute(
        select(func.count()).select_from(TankCalibrationPoint).where(TankCalibrationPoint.tankId == tank.id)
    )
    has_points = (count_result.scalar_one() or 0) > 0
    if not has_points:
        await alerts_service.upsert_active_alert(
            db, station_id=tank.stationId, tank_id=tank.id, alert_type="calibration_missing", triggered_at=now,
        )
    else:
        await alerts_service.auto_resolve_alert(
            db, station_id=tank.stationId, tank_id=tank.id, product_id=None,
            alert_type="calibration_missing", resolved_at=now,
        )


async def evaluate_station_offline_alert(db: AsyncSession, station: Station, tanks: list[Tank]) -> None:
    """Une station dont AUCUNE cuve configurée (mapping capteur actif
    `product_level` ayant déjà reçu au moins une mesure) ne transmet plus de
    données est en silence complet — jamais remontée comme alerte dédiée
    jusqu'ici, alors qu'une action rapide (contacter la station) serait
    utile (P1-9, audit module Stations 2026-09-16). Critère volontairement
    plus strict que le badge « en ligne » de la liste des stations
    (`computeStationOnlineStatus` côté frontend, P0-5 : TOUTES les cuves
    configurées en ligne) — une seule cuve en défaut ne doit pas déclencher
    une alerte « contacter la station », réservée au silence total."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    configured_count = 0
    online_count = 0
    for tank in tanks:
        registry = await _get_active_registry_entry(db, tank.id, "product_level")
        if registry is None or registry.lastValue is None:
            continue
        configured_count += 1
        if registry.hkLastStatus == 1:
            online_count += 1

    if configured_count > 0 and online_count == 0:
        await alerts_service.upsert_active_alert(db, station_id=station.id, alert_type="station_offline", triggered_at=now)
    else:
        await alerts_service.auto_resolve_alert(
            db, station_id=station.id, tank_id=None, product_id=None, alert_type="station_offline", resolved_at=now,
        )


async def evaluate_structural_alerts_for_organization(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Un balayage périodique (pas piloté par la télémétrie, contrairement à
    `run_alert_evaluation_for_tank`) — toutes les stations de l'organisation,
    toutes leurs cuves actives, tous leurs produits vendus actifs."""
    stations = (await db.execute(select(Station).where(Station.organizationId == organization_id))).scalars().all()
    for station in stations:
        links = (await db.execute(
            select(StationFuelProduct).where(StationFuelProduct.stationId == station.id, StationFuelProduct.active == True)  # noqa: E712
        )).scalars().all()
        for link in links:
            await evaluate_price_missing_alert(db, station.id, link.fuelProductId)

        tanks = (await db.execute(
            select(Tank).where(Tank.stationId == station.id, Tank.active == True)  # noqa: E712
        )).scalars().all()
        for tank in tanks:
            await evaluate_sensor_mapping_missing_alert(db, tank)
            await evaluate_calibration_missing_alert(db, tank)
        await evaluate_station_offline_alert(db, station, tanks)
    await db.commit()


async def _measurement_at_or_before(
    db: AsyncSession, tank_id: uuid.UUID, measurement_type: str, at, sensor_ids: list[int] | None = None
) -> float | None:
    """Dernière mesure connue avant ou égale à l'instant demandé, jamais une
    mesure postérieure (Point 2 §5.4). Honore une éventuelle correction
    (`TankMeasurement.isCorrection`/`correctsMeasurementId`, audit
    Caisse P1 §D.1) : si la mesure trouvée a été corrigée depuis, la valeur
    de la correction remplace la valeur brute d'origine — jamais les deux
    traitées comme deux mesures indépendantes.

    `sensor_ids` (audit performance 2026-09-11) : quand fourni par
    l'appelant (déjà résolus une fois pour toute la cuve, cet appel étant
    répété à chaque frontière de segment de caisse), évite de refaire la
    requête `TankSensorMapping` à chaque appel."""
    if sensor_ids is None:
        sensor_ids_result = await db.execute(
            select(TankSensorMapping.hkSensorId).where(
                TankSensorMapping.tankId == tank_id, TankSensorMapping.measurementType == measurement_type
            )
        )
        sensor_ids = [row[0] for row in sensor_ids_result.all()]
    if not sensor_ids:
        return None
    result = await db.execute(
        select(TankMeasurement.id, TankMeasurement.rawValue)
        .where(TankMeasurement.hkSensorId.in_(sensor_ids), TankMeasurement.measuredAt <= at)
        .order_by(TankMeasurement.measuredAt.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    measurement_id, raw_value = row

    correction_result = await db.execute(
        select(TankMeasurement.rawValue)
        .where(TankMeasurement.correctsMeasurementId == measurement_id, TankMeasurement.isCorrection.is_(True))
        .order_by(TankMeasurement.insertedAt.desc())
        .limit(1)
    )
    correction = correction_result.scalar_one_or_none()
    return float(correction) if correction is not None else float(raw_value)


async def get_network_snapshot(db: AsyncSession, organization_id: uuid.UUID, at) -> NetworkSummaryResponse:
    """État reconstitué du réseau à un instant passé (Point 2 §5.4) — même
    structure de réponse que l'endpoint 9 (network/summary), mais résolue
    depuis l'historique `TankMeasurement` plutôt que depuis
    `HolykellDeviceRegistry.lastValue` (instant présent). Réutilise
    `interpolate_height_to_volume`, déjà validé à l'endpoint 7."""
    at = _to_naive_utc(at)
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
        # même plancher à 0 qu'en get_tank_current_state : bruit de mesure
        # entre les deux capteurs indépendants (produit/eau) près du vide.
        volume_net = max(0.0, volume_brut - water_volume)

        entry = _init_product_entry(per_product, tank.fuelProductId)
        entry["stations"].add(tank.stationId)
        entry["tanks"] += 1
        entry["volume"] += volume_net
        all_stations_with_data.add(tank.stationId)

        monetary_value, currency_code, _, _ = await _resolve_tank_monetary_value(db, tank, volume_net, at)
        # Volume vendable non calculé pour un instantané historique (pas de
        # seuil bas interpolé ici) — hors périmètre de cet endpoint, jamais
        # une valeur inventée : les lignes produit du snapshot gardent
        # `totalSellableVolumeLiters=0`/`totalSellableMonetaryValue=None`.
        _accumulate_monetary(entry, monetary_value, None, currency_code)

    products = _build_product_lines(per_product, fuel_products_by_id)
    # Le volume vendable à un instant passé n'est pas calculé par ce
    # snapshot (pas d'interpolation du seuil bas ici) — `0` serait un
    # mensonge ("rien de vendable") plutôt qu'une absence de calcul :
    # forcé à `None` plutôt que la fausse valeur `0.0` que produirait
    # `_build_product_lines` faute de mieux.
    products = [p.model_copy(update={"totalSellableMonetaryValue": None}) for p in products]

    return NetworkSummaryResponse(
        products=products,
        totalVolumeLiters=sum(p.totalVolumeLiters for p in products),
        totalStationCount=len(all_stations_with_data),
        totalTankCount=sum(p.tankCount for p in products),
    )


async def _resolve_station_default_currency(db: AsyncSession, station: Station) -> Currency:
    """Devise par défaut d'une station : `Station.currencyOverrideId` en
    priorité s'il est fixé (dérogation explicite — page_caisse_configuration
    audit P1 §E.4, inspirée de `currency_override_id` de l'ancien Zylo/Odoo),
    sinon Station.cityId -> City -> Region -> Country.currencyCode (chaîne
    déjà existante) -> Currency correspondante (endpoint 14). Jamais une
    devise inventée si la chaîne est incomplète ou si la Currency n'existe
    pas encore (Point 2 Chapitre 7 introduction, niveau_1_...md §17-18)."""
    if station.currencyOverrideId is not None:
        override = await db.get(Currency, station.currencyOverrideId)
        if override is not None:
            return override
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
    # FK réelle en priorité (audit Configuration carburant P1 §E.5) — repli
    # sur la chaîne `currencyCode` uniquement pour un pays jamais rattaché
    # (compatibilité avec un référentiel géographique antérieur à ce
    # rattachement, jamais le chemin normal une fois le seed exécuté).
    currency = await db.get(Currency, country.currencyId) if country.currencyId is not None else None
    if currency is None:
        currency_result = await db.execute(select(Currency).where(Currency.code == country.currencyCode))
        currency = currency_result.scalar_one_or_none()
    if currency is None:
        raise AppError(
            code="currency_not_found",
            message=f"La devise par défaut de cette station ('{country.currencyCode}') n'existe pas encore dans le référentiel — la créer via POST /currencies avant d'enregistrer un prix.",
            status_code=422,
        )
    return currency


async def _resolve_station_currencies_batch(db: AsyncSession, stations: list[Station]) -> dict[uuid.UUID, Currency | None]:
    """Version batchée de `_resolve_station_default_currency` (audit
    performance 2026-09-11) : un aller-retour DB par étape de la chaîne
    (dérogation, ville, région, pays, devise) pour TOUTES les stations
    demandées, au lieu d'un aller-retour par étape PAR STATION — cette
    chaîne, appelée une fois par cuve via `_resolve_applicable_price`, était
    un contributeur majeur des lenteurs mesurées (jusqu'à 4 requêtes
    supplémentaires par cuve rien que pour retomber sur le prix réseau par
    défaut). Retourne `None` pour une station dont la devise n'est pas
    résolvable, jamais une exception — reproduit exactement le
    `except AppError: pass` déjà présent chez l'appelant historique."""
    if not stations:
        return {}

    result: dict[uuid.UUID, Currency | None] = {}
    remaining: list[Station] = []

    override_ids = {s.currencyOverrideId for s in stations if s.currencyOverrideId is not None}
    override_by_id: dict[uuid.UUID, Currency] = {}
    if override_ids:
        override_result = await db.execute(select(Currency).where(Currency.id.in_(override_ids)))
        override_by_id = {c.id: c for c in override_result.scalars().all()}

    for station in stations:
        if station.currencyOverrideId is not None and station.currencyOverrideId in override_by_id:
            result[station.id] = override_by_id[station.currencyOverrideId]
        else:
            remaining.append(station)

    if not remaining:
        return result

    city_ids = {s.cityId for s in remaining if s.cityId is not None}
    cities_by_id: dict[uuid.UUID, City] = {}
    if city_ids:
        city_result = await db.execute(select(City).where(City.id.in_(city_ids)))
        cities_by_id = {c.id: c for c in city_result.scalars().all()}

    region_ids = {c.regionId for c in cities_by_id.values()}
    regions_by_id: dict[uuid.UUID, Region] = {}
    if region_ids:
        region_result = await db.execute(select(Region).where(Region.id.in_(region_ids)))
        regions_by_id = {r.id: r for r in region_result.scalars().all()}

    country_ids = {r.countryId for r in regions_by_id.values()}
    countries_by_id: dict[uuid.UUID, Country] = {}
    if country_ids:
        country_result = await db.execute(select(Country).where(Country.id.in_(country_ids)))
        countries_by_id = {c.id: c for c in country_result.scalars().all()}

    currency_ids = {c.currencyId for c in countries_by_id.values() if c.currencyId is not None}
    currency_codes = {c.currencyCode for c in countries_by_id.values()}
    currencies_by_id: dict[uuid.UUID, Currency] = {}
    currencies_by_code: dict[str, Currency] = {}
    if currency_ids:
        currency_result = await db.execute(select(Currency).where(Currency.id.in_(currency_ids)))
        currencies_by_id = {c.id: c for c in currency_result.scalars().all()}
    if currency_codes:
        code_result = await db.execute(select(Currency).where(Currency.code.in_(currency_codes)))
        currencies_by_code = {c.code: c for c in code_result.scalars().all()}

    for station in remaining:
        city = cities_by_id.get(station.cityId) if station.cityId is not None else None
        region = regions_by_id.get(city.regionId) if city is not None else None
        country = countries_by_id.get(region.countryId) if region is not None else None
        currency: Currency | None = None
        if country is not None:
            if country.currencyId is not None:
                currency = currencies_by_id.get(country.currencyId)
            if currency is None:
                currency = currencies_by_code.get(country.currencyCode)
        result[station.id] = currency

    return result


async def _resolve_applicable_prices_batch(
    db: AsyncSession, pairs: set[tuple[uuid.UUID, uuid.UUID]], stations_by_id: dict[uuid.UUID, Station], at
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[PriceHistory | None, str | None]]:
    """Version batchée de `_resolve_applicable_price` — même sémantique
    exacte (prix propre à la station en priorité, repli sur le prix réseau
    par défaut filtré par la devise de la station quand elle est
    résolvable, puis distinction `price_currency_mismatch` vs
    `no_applicable_price` — voir `_resolve_applicable_price`), mais un
    aller-retour DB par étape pour l'ensemble des paires (station, produit)
    demandées plutôt qu'un aller-retour par paire (audit performance
    2026-09-11)."""
    if not pairs:
        return {}

    station_ids = {station_id for station_id, _ in pairs}
    product_ids = {product_id for _, product_id in pairs}
    stations = [stations_by_id[sid] for sid in station_ids if sid in stations_by_id]
    currency_by_station = await _resolve_station_currencies_batch(db, stations)

    station_price_result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.stationId.in_(station_ids), PriceHistory.fuelProductId.in_(product_ids), PriceHistory.effectiveFrom <= at)
        .order_by(PriceHistory.effectiveFrom.desc())
    )
    station_price_by_key: dict[tuple[uuid.UUID, uuid.UUID], PriceHistory] = {}
    for price in station_price_result.scalars().all():
        key = (price.stationId, price.fuelProductId)
        if key not in station_price_by_key:
            station_price_by_key[key] = price

    default_price_result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.stationId.is_(None), PriceHistory.fuelProductId.in_(product_ids), PriceHistory.effectiveFrom <= at)
        .order_by(PriceHistory.effectiveFrom.desc())
    )
    default_prices = list(default_price_result.scalars().all())

    resolved: dict[tuple[uuid.UUID, uuid.UUID], tuple[PriceHistory | None, str | None]] = {}
    for station_id, product_id in pairs:
        key = (station_id, product_id)
        price = station_price_by_key.get(key)
        reason: str | None = None
        if price is None:
            any_currency_candidates = [p for p in default_prices if p.fuelProductId == product_id]
            candidates = any_currency_candidates
            station_currency = currency_by_station.get(station_id)
            if station_currency is not None:
                candidates = [p for p in candidates if p.currencyId == station_currency.id]
            price = candidates[0] if candidates else None
            if price is None:
                reason = "price_currency_mismatch" if (station_currency is not None and any_currency_candidates) else "no_applicable_price"
        resolved[key] = (price, reason)

    return resolved


class _CashPriceContext:
    """Pré-chargement des prix réseau par défaut et de la devise résolue
    d'une station (audit performance 2026-09-11) — évite de refaire la
    chaîne complète `_resolve_applicable_price`/`_resolve_station_default_
    currency` (jusqu'à 6 requêtes) à CHAQUE frontière de segment de vente,
    potentiellement plusieurs fois par cuve et par jour. Construit une seule
    fois pour tout le réseau/toute la station, jamais par cuve. Optionnel
    partout où il est accepté : en son absence, l'ancienne résolution
    ponctuelle par requête reste utilisée (comportement inchangé pour les
    appelants non batchés, ex. `get_tank_cash` sur une seule cuve)."""

    def __init__(self, default_prices: list[PriceHistory], station_currency: Currency | None, currency_code_by_id: dict[uuid.UUID, str]):
        self.default_prices = default_prices
        self.station_currency = station_currency
        self.currency_code_by_id = currency_code_by_id


async def _build_cash_price_contexts(db: AsyncSession, tanks: list[Tank]) -> dict[uuid.UUID, "_CashPriceContext"]:
    """Construit un `_CashPriceContext` par cuve à partir d'un seul jeu de
    requêtes groupées pour l'ensemble des cuves demandées (audit
    performance 2026-09-11) — jamais une résolution par cuve. Les prix par
    défaut ne dépendent que du produit, la devise que de la station : les
    deux sont donc calculés une fois pour tout l'ensemble, puis recombinés
    en mémoire par cuve."""
    if not tanks:
        return {}

    fuel_product_ids = {t.fuelProductId for t in tanks}
    station_ids = {t.stationId for t in tanks}

    default_price_result = await db.execute(
        select(PriceHistory).where(PriceHistory.stationId.is_(None), PriceHistory.fuelProductId.in_(fuel_product_ids))
    )
    default_prices_by_product: dict[uuid.UUID, list[PriceHistory]] = {}
    for p in default_price_result.scalars().all():
        default_prices_by_product.setdefault(p.fuelProductId, []).append(p)

    stations_result = await db.execute(select(Station).where(Station.id.in_(station_ids)))
    stations = list(stations_result.scalars().all())
    currency_by_station = await _resolve_station_currencies_batch(db, stations)

    all_currencies_result = await db.execute(select(Currency))
    currency_code_by_id = {c.id: c.code for c in all_currencies_result.scalars().all()}

    contexts: dict[uuid.UUID, _CashPriceContext] = {}
    for tank in tanks:
        contexts[tank.id] = _CashPriceContext(
            default_prices=default_prices_by_product.get(tank.fuelProductId, []),
            station_currency=currency_by_station.get(tank.stationId),
            currency_code_by_id=currency_code_by_id,
        )
    return contexts


def _price_at_or_before(price_rows: list[PriceHistory], at) -> PriceHistory | None:
    """Parmi des lignes `PriceHistory` déjà chargées (jamais une nouvelle
    requête), celle dont `effectiveFrom` est la plus récente antérieure ou
    égale à `at` — même sémantique que la clause `ORDER BY effectiveFrom
    DESC LIMIT 1` de `_resolve_applicable_price`, mais en mémoire."""
    applicable = [p for p in price_rows if p.effectiveFrom <= at]
    if not applicable:
        return None
    return max(applicable, key=lambda p: p.effectiveFrom)


async def create_price_history(
    db: AsyncSession, organization_id: uuid.UUID, created_by: uuid.UUID, data: CreatePriceHistoryRequest
) -> PriceHistoryResponse:
    station = await get_station(db, organization_id, data.stationId) if data.stationId is not None else None
    await get_fuel_product(db, organization_id, data.fuelProductId)

    # Scoping par station (Phase 4 §4 de refonte-configuration-zylo-liquid.md,
    # gap identifié en Phase 1 §1.6) : `stationId` vient du corps de la
    # requête, jamais du chemin — le mécanisme générique
    # `require_permission_scoped_via` (qui ne lit que `request.path_params`)
    # ne peut pas s'appliquer ici, d'où cette vérification explicite. Un prix
    # par défaut réseau (`station is None`) reste vérifié à l'échelle de
    # l'organisation entière (comportement inchangé, cohérent avec le fait
    # qu'aucune station ne borne sa portée).
    allowed = await user_has_permission(
        db, created_by, organization_id, PRICE_HISTORY_CREATE,
        "station" if station is not None else None,
        station.id if station is not None else None,
    )
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PRICE_HISTORY_CREATE}.", status_code=403)

    # Même bug que list_deliveries/list_alerts/etc. (voir _to_naive_utc) :
    # `effectiveFrom` arrive "aware" quand le frontend envoie
    # `Date.toISOString()` — normalisé ici avant toute comparaison/insertion.
    effective_from = _to_naive_utc(data.effectiveFrom)

    if data.currencyId is not None:
        currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
        if currency_result.scalar_one_or_none() is None:
            raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
        currency_id = data.currencyId
    elif station is not None:
        currency = await _resolve_station_default_currency(db, station)
        currency_id = currency.id
    else:
        # Prix par défaut réseau (audit Configuration carburant P2 §E) :
        # aucune station dont dériver une devise — doit être fournie
        # explicitement, jamais devinée (quelle devise pour un réseau
        # multi-pays ?).
        raise AppError(
            code="currency_required_for_network_default",
            message="currencyId est obligatoire pour un prix par défaut réseau (aucune station dont déduire une devise).",
            status_code=422,
        )

    existing_conditions = [
        PriceHistory.stationId.is_(None) if data.stationId is None else PriceHistory.stationId == data.stationId,
        PriceHistory.fuelProductId == data.fuelProductId,
        PriceHistory.effectiveFrom == effective_from,
    ]
    if data.stationId is None:
        # Prix par défaut réseau : la contrainte DB (refonte multi-devise,
        # Phase 4 §1 de refonte-configuration-zylo-liquid.md) autorise
        # désormais plusieurs devises simultanées pour un même produit/date —
        # le conflit ne porte donc que sur la même devise, jamais toutes
        # devises confondues.
        existing_conditions.append(PriceHistory.currencyId == currency_id)
    existing = await db.execute(select(PriceHistory).where(*existing_conditions))
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
    await db.flush()

    fuel_product = await get_fuel_product(db, organization_id, data.fuelProductId)
    scope_label = station.name if station is not None else "réseau (défaut)"
    await record_audit_event(
        db,
        organization_id,
        created_by,
        action="zyloLiquid.price.update",
        entity_type="PriceHistory",
        entity_id=price.id,
        summary=f"Prix {fuel_product.name} modifié ({scope_label}) : {data.priceAmount}",
        changes={"priceAmount": {"after": str(data.priceAmount)}, "effectiveFrom": str(effective_from)},
        scope_resource_type="station" if station is not None else None,
        scope_resource_id=station.id if station is not None else None,
    )
    await db.commit()
    await db.refresh(price)

    is_future = price.effectiveFrom > datetime.now(timezone.utc).replace(tzinfo=None)
    return PriceHistoryResponse.model_validate(price).model_copy(update={"isFuture": is_future})


async def _get_price_history_and_station(db: AsyncSession, organization_id: uuid.UUID, price_id: uuid.UUID) -> PriceHistory:
    # Jointure via FuelProduct plutôt que Station : un prix par défaut
    # réseau (audit Configuration carburant P2 §E) a `stationId IS NULL`,
    # une jointure INNER sur Station l'exclurait toujours — `fuelProductId`,
    # lui, est renseigné sur toute ligne, station précise ou défaut réseau.
    result = await db.execute(
        select(PriceHistory)
        .join(FuelProduct, FuelProduct.id == PriceHistory.fuelProductId)
        .where(PriceHistory.id == price_id, FuelProduct.organizationId == organization_id)
    )
    price = result.scalar_one_or_none()
    if price is None:
        raise AppError(code="price_history_not_found", message="Ligne de prix introuvable.", status_code=404)
    return price


async def update_price_history(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, price_id: uuid.UUID, data: UpdatePriceHistoryRequest
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
    before = {field: str(getattr(price, field)) for field in updates}
    for field, value in updates.items():
        setattr(price, field, value)
    fuel_product = await get_fuel_product(db, organization_id, price.fuelProductId)
    # Contrairement à la création (create_price_history), aucun événement
    # d'audit n'était jamais enregistré ici — une correction de prix
    # n'avait donc aucun horodatage traçable du tout (P0-6, audit module
    # Stations 2026-09-16).
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.price.correct",
        entity_type="PriceHistory",
        entity_id=price.id,
        summary=f"Correction du prix {fuel_product.name}",
        changes={field: {"before": before[field], "after": str(value)} for field, value in updates.items()},
        scope_resource_type="station" if price.stationId is not None else None,
        scope_resource_id=price.stationId,
    )
    await db.commit()
    await db.refresh(price)
    return PriceHistoryResponse.model_validate(price)


async def list_price_history(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    fuel_product_id: uuid.UUID | None,
    from_date,
    to_date,
) -> Page:
    from_date = _to_naive_utc(from_date)
    to_date = _to_naive_utc(to_date)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    # Portée par station (Phase 4 §4) : un utilisateur restreint à certaines
    # stations ne doit voir ni les lignes des autres stations, ni pouvoir les
    # cibler via `station_id` — les prix par défaut réseau (stationId NULL)
    # restent visibles dès qu'il a AU MOINS une portée sur PRICE_HISTORY_READ
    # (ils s'appliquent potentiellement à toute station qu'il gère).
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, PRICE_HISTORY_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PRICE_HISTORY_READ}.", status_code=403)
    if station_id is not None and not sees_all and station_id not in visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PRICE_HISTORY_READ}.", status_code=403)

    # Jointure via FuelProduct (jamais Station, cf. _get_price_history_and_station) :
    # inclut aussi les prix par défaut réseau (stationId NULL) de
    # l'organisation, qu'une jointure INNER sur Station exclurait toujours.
    stmt = (
        select(PriceHistory)
        .join(FuelProduct, FuelProduct.id == PriceHistory.fuelProductId)
        .where(FuelProduct.organizationId == organization_id)
    )
    if not sees_all:
        stmt = stmt.where(PriceHistory.stationId.in_(visible_station_ids) | PriceHistory.stationId.is_(None))
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


async def list_holykell_accounts(db: AsyncSession, organization_id: uuid.UUID) -> list[HolykellAccount]:
    """Liste des comptes Holykell de l'organisation — permet au frontend de
    retrouver l'état de synchro (lastSyncAt) sans connaître à l'avance l'ID
    du compte (en pratique un seul compte par organisation)."""
    result = await db.execute(select(HolykellAccount).where(HolykellAccount.organizationId == organization_id))
    return list(result.scalars().all())


# ================================================================
# CAISSE (page_caisse.md, validé avant implémentation) — ventes estimées à
# partir des baisses de niveau mesurées, jamais un état comptable officiel.
# Rien n'est persisté : tout est recalculé à la demande depuis
# TankMeasurement/DeliveryDetected/PriceHistory (page_caisse.md §31, pas de
# pré-agrégation en P0). Les livraisons ne sont jamais recalculées ici —
# uniquement lues depuis DeliveryDetected, déjà maintenu par
# run_delivery_detection_for_tank (page_caisse.md §F).
# ================================================================

_CASH_CONFIDENCE_RANK = {"reliable": 0, "partial": 1, "incomplete_data": 2, "insufficient_data": 3, "anomaly": 4}


def _worse_cash_confidence(a: str, b: str) -> str:
    """Ne jamais moyenner ni masquer une dégradation de confiance
    (page_caisse.md §21/§D.3) — la pire valeur des deux gagne toujours."""
    return a if _CASH_CONFIDENCE_RANK[a] >= _CASH_CONFIDENCE_RANK[b] else b


async def _cash_boundary_height_and_volume(
    db: AsyncSession, tank_id: uuid.UUID, calibration_points: list[tuple[float, float]], at: datetime, sensor_ids: list[int] | None = None
) -> tuple[float | None, float | None]:
    """Hauteur/volume à une borne de segment, lus depuis la dernière mesure
    réelle connue avant ou à cet instant (jamais une mesure future) —
    réutilise `_measurement_at_or_before`, jamais une deuxième requête
    dupliquée (page_caisse.md §D.1).

    `sensor_ids` (audit performance 2026-09-11) : capteurs "product_level"
    de cette cuve déjà résolus une fois par `_compute_tank_cash` — cette
    fonction étant appelée à chaque frontière de segment (parfois
    plusieurs fois par cuve), évite de refaire la résolution à chaque appel."""
    height = await _measurement_at_or_before(db, tank_id, "product_level", at, sensor_ids)
    if height is None:
        return None, None
    return height, interpolate_height_to_volume(calibration_points, height)


async def _price_sub_segments_for_sale_window(
    db: AsyncSession,
    tank: Tank,
    calibration_points: list[tuple[float, float]],
    window_start: datetime,
    window_end: datetime,
    start_height: float,
    start_volume: float,
    end_height: float,
    end_volume: float,
    price_changes_in_range: list[PriceHistory],
    price_context: _CashPriceContext | None = None,
    sensor_ids: list[int] | None = None,
) -> tuple[list[dict], float, float | None, str | None, str | None]:
    """Découpe un segment de vente à chaque changement de prix qui tombe
    strictement à l'intérieur (page_caisse.md §D.2/§G) : jamais un seul prix
    appliqué à toute une fenêtre qui a vu un changement. La hauteur à
    l'instant du changement est lue depuis une vraie mesure
    (`_measurement_at_or_before`), jamais une interpolation temporelle
    fictive, sauf si aucune mesure n'est disponible à cet instant précis (cas
    dégradé, alors interpolée linéairement dans le temps entre les deux
    bornes connues — limitation assumée, page_caisse.md §G).

    Retourne (segments, volume_total, valeur_monétaire|None, devise|None,
    raison_de_non_calcul|None)."""
    boundary_times = sorted({t.effectiveFrom for t in price_changes_in_range if window_start < t.effectiveFrom < window_end})

    segments: list[dict] = []
    total_volume = 0.0
    total_monetary = 0.0
    currency_code: str | None = None
    reason: str | None = None

    prev_t, prev_h, prev_v = window_start, start_height, start_volume
    boundary_times.append(window_end)
    for t in boundary_times:
        if t == window_end:
            h, v = end_height, end_volume
        else:
            h, v = await _cash_boundary_height_and_volume(db, tank.id, calibration_points, t, sensor_ids)
            if v is None:
                # Aucune mesure exactement à cet instant (rare) -> repli sur
                # une interpolation temporelle linéaire entre les deux
                # bornes déjà connues de la fenêtre, explicitement une
                # approximation (page_caisse.md §G).
                ratio = (t - window_start).total_seconds() / (window_end - window_start).total_seconds()
                h = start_height + (end_height - start_height) * ratio
                v = interpolate_height_to_volume(calibration_points, h)

        sub_volume = max(0.0, (prev_v or 0.0) - (v or 0.0))

        if price_context is not None:
            # Résolution en mémoire à partir des lignes déjà chargées pour
            # tout le réseau/la station — jamais de requête ici (audit
            # performance 2026-09-11) : `price_changes_in_range` couvre déjà
            # le prix propre à la station, `price_context.default_prices`
            # le repli réseau, exactement les deux mêmes sources que
            # `_resolve_applicable_price`, juste précalculées.
            price_at = _price_at_or_before(price_changes_in_range, t)
            if price_at is None:
                candidates = [p for p in price_context.default_prices if p.effectiveFrom <= t]
                if price_context.station_currency is not None:
                    candidates = [p for p in candidates if p.currencyId == price_context.station_currency.id]
                price_at = max(candidates, key=lambda p: p.effectiveFrom) if candidates else None
            sub_currency = price_context.currency_code_by_id.get(price_at.currencyId) if price_at is not None else None
        else:
            price_at, _ = await _resolve_applicable_price(db, tank.stationId, tank.fuelProductId, t)
            sub_currency = None
            if price_at is not None:
                currency = await db.get(Currency, price_at.currencyId)
                sub_currency = currency.code if currency else None

        sub_monetary: float | None = None
        sub_reason: str | None = None
        if price_at is None:
            sub_reason = "no_applicable_price"
            reason = reason or "no_applicable_price"
        else:
            if currency_code is not None and sub_currency != currency_code:
                reason = "mixed_currencies"
            else:
                currency_code = sub_currency
                sub_monetary = sub_volume * float(price_at.priceAmount)
                total_monetary += sub_monetary

        total_volume += sub_volume
        segments.append(
            {
                "startTime": prev_t,
                "endTime": t,
                "type": "sale",
                "startHeightMm": prev_h,
                "endHeightMm": h,
                "startVolumeLiters": prev_v,
                "endVolumeLiters": v,
                "volumeLiters": sub_volume,
                "monetaryValue": sub_monetary,
                "currencyCode": sub_currency,
                "monetaryValueNotCalculableReason": sub_reason,
            }
        )
        prev_t, prev_h, prev_v = t, h, v

    final_monetary = None if reason is not None else total_monetary
    return segments, total_volume, final_monetary, (currency_code if reason is None else None), reason


async def _compute_tank_cash(
    db: AsyncSession, tank: Tank, period_start: datetime, period_end: datetime, price_context: _CashPriceContext | None = None
) -> dict:
    """Moteur de segmentation + valorisation pour une cuve sur une période
    (page_caisse.md §D.1-§D.2) : lit les mesures et les livraisons déjà
    détectées, découpe la période en segments vente/livraison/anomalie,
    valorise chaque segment de vente au prix applicable à son instant.
    Ne modifie jamais aucune donnée — lecture seule.

    `price_context` (audit performance 2026-09-11) : quand fourni par
    l'appelant (réseau/station, où les mêmes prix réseau par défaut et la
    même devise de station s'appliquent à toutes les cuves), la résolution
    de prix se fait en mémoire plutôt que par une requête par frontière de
    segment — voir `_price_sub_segments_for_sale_window`."""
    calibration_result = await db.execute(
        select(TankCalibrationPoint.heightMm, TankCalibrationPoint.volumeLiters).where(TankCalibrationPoint.tankId == tank.id)
    )
    calibration_points = [(float(h), float(v)) for h, v in calibration_result.all()]
    if not calibration_points:
        return {
            "tankId": tank.id,
            "stationId": tank.stationId,
            "fuelProductId": tank.fuelProductId,
            "volumeSoldLiters": None,
            "volumeNotCalculableReason": "no_calibration_table",
            "monetaryValue": None,
            "currencyCode": None,
            "monetaryValueNotCalculableReason": "no_calibration_table",
            "confidence": "insufficient_data",
            "anomalyTypes": [],
            "segments": [],
        }

    # Capteurs "product_level" de cette cuve, résolus une seule fois — sinon
    # `_measurement_at_or_before` refait cette même requête à chaque frontière
    # de segment (audit performance 2026-09-11).
    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(
            TankSensorMapping.tankId == tank.id, TankSensorMapping.measurementType == "product_level"
        )
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]

    deliveries_result = await db.execute(
        select(DeliveryDetected)
        .where(DeliveryDetected.tankId == tank.id, DeliveryDetected.startTime < period_end, DeliveryDetected.endTime > period_start)
        .order_by(DeliveryDetected.startTime)
    )
    deliveries = deliveries_result.scalars().all()

    price_history_result = await db.execute(
        select(PriceHistory).where(PriceHistory.stationId == tank.stationId, PriceHistory.fuelProductId == tank.fuelProductId)
    )
    price_history_rows = price_history_result.scalars().all()

    segments: list[dict] = []
    anomaly_types: list[str] = []
    confidence = "reliable"
    total_volume = 0.0
    total_monetary = 0.0
    currency_code: str | None = None
    pricing_reason: str | None = None
    any_volume_calculated = False

    cursor = period_start
    cursor_height: float | None = None
    cursor_volume: float | None = None

    async def resolve_sale_window(window_start: datetime, window_end: datetime, h_start, v_start, h_end, v_end) -> None:
        nonlocal total_volume, total_monetary, currency_code, pricing_reason, confidence, any_volume_calculated
        if v_start is None or v_end is None:
            segments.append(
                {
                    "startTime": window_start,
                    "endTime": window_end,
                    "type": "insufficient_data",
                    "startHeightMm": h_start,
                    "endHeightMm": h_end,
                    "startVolumeLiters": v_start,
                    "endVolumeLiters": v_end,
                    "volumeLiters": 0.0,
                    "monetaryValue": None,
                    "currencyCode": None,
                    "monetaryValueNotCalculableReason": "insufficient_data",
                }
            )
            confidence = _worse_cash_confidence(confidence, "incomplete_data")
            return

        any_volume_calculated = True
        duration_hours = (window_end - window_start).total_seconds() / 3600
        variation_type, _ = classify_tank_variation(v_start, v_end, duration_hours)

        if variation_type != "sale":
            segments.append(
                {
                    "startTime": window_start,
                    "endTime": window_end,
                    "type": variation_type,
                    "startHeightMm": h_start,
                    "endHeightMm": h_end,
                    "startVolumeLiters": v_start,
                    "endVolumeLiters": v_end,
                    "volumeLiters": 0.0,
                    "monetaryValue": None,
                    "currencyCode": None,
                    "monetaryValueNotCalculableReason": None,
                }
            )
            if variation_type.startswith("anomaly_"):
                anomaly_types.append(variation_type)
                confidence = _worse_cash_confidence(confidence, "anomaly")
            return

        sub_segments, volume, monetary, code, reason = await _price_sub_segments_for_sale_window(
            db, tank, calibration_points, window_start, window_end, h_start, v_start, h_end, v_end, price_history_rows, price_context, sensor_ids
        )
        segments.extend(sub_segments)
        total_volume += volume
        if reason is not None:
            pricing_reason = pricing_reason or reason
        elif code is not None:
            if currency_code is not None and code != currency_code:
                pricing_reason = "mixed_currencies"
            else:
                currency_code = code
                total_monetary += monetary or 0.0

    for delivery in deliveries:
        clipped_start = max(delivery.startTime, period_start)
        clipped_end = min(delivery.endTime, period_end)
        if clipped_end <= clipped_start:
            continue

        if clipped_start > cursor:
            if cursor_volume is None:
                cursor_height, cursor_volume = await _cash_boundary_height_and_volume(db, tank.id, calibration_points, cursor, sensor_ids)
            end_height = float(delivery.startHeightMm)
            end_volume = float(delivery.startVolumeLiters) if delivery.startVolumeLiters is not None else interpolate_height_to_volume(
                calibration_points, end_height
            )
            await resolve_sale_window(cursor, clipped_start, cursor_height, cursor_volume, end_height, end_volume)

        delivery_volume = float(delivery.volumeLiters) if delivery.volumeLiters is not None else None
        segments.append(
            {
                "startTime": clipped_start,
                "endTime": clipped_end,
                "type": "delivery",
                "startHeightMm": float(delivery.startHeightMm),
                "endHeightMm": float(delivery.endHeightMm),
                "startVolumeLiters": float(delivery.startVolumeLiters) if delivery.startVolumeLiters is not None else None,
                "endVolumeLiters": float(delivery.endVolumeLiters) if delivery.endVolumeLiters is not None else None,
                "volumeLiters": delivery_volume or 0.0,
                "monetaryValue": None,
                "currencyCode": None,
                "monetaryValueNotCalculableReason": None,
            }
        )

        cursor = clipped_end
        cursor_height = float(delivery.endHeightMm)
        cursor_volume = float(delivery.endVolumeLiters) if delivery.endVolumeLiters is not None else interpolate_height_to_volume(
            calibration_points, cursor_height
        )

    if cursor < period_end:
        if cursor_volume is None:
            cursor_height, cursor_volume = await _cash_boundary_height_and_volume(db, tank.id, calibration_points, cursor, sensor_ids)
        end_height, end_volume = await _cash_boundary_height_and_volume(db, tank.id, calibration_points, period_end, sensor_ids)
        await resolve_sale_window(cursor, period_end, cursor_height, cursor_volume, end_height, end_volume)

    if not any_volume_calculated:
        volume_sold: float | None = None
        volume_reason: str | None = "insufficient_data"
        confidence = "insufficient_data"
    else:
        volume_sold = total_volume
        volume_reason = None

    if pricing_reason is not None:
        monetary_value, monetary_reason = None, pricing_reason
        if confidence == "reliable":
            confidence = "partial"
    elif volume_sold is None:
        monetary_value, monetary_reason = None, "insufficient_data"
    else:
        monetary_value, monetary_reason = total_monetary, None

    return {
        "tankId": tank.id,
        "stationId": tank.stationId,
        "fuelProductId": tank.fuelProductId,
        "volumeSoldLiters": volume_sold,
        "volumeNotCalculableReason": volume_reason,
        "monetaryValue": monetary_value,
        "currencyCode": currency_code if monetary_value is not None else None,
        "monetaryValueNotCalculableReason": monetary_reason,
        "confidence": confidence,
        "anomalyTypes": anomaly_types,
        "segments": segments,
    }


# Tolérance avant de rejeter une période comme "future" : le `toDate` d'une
# requête "Aujourd'hui" est calculé côté navigateur (`new Date()`), puis
# comparé ici à l'horloge serveur — un léger décalage d'horloge entre les
# deux hôtes (ou simplement la latence réseau de la requête) suffit sinon à
# déclencher un rejet pourtant illégitime (aucune marge n'existait avant ce
# correctif). Une valeur légèrement future est de toute façon sans
# conséquence pour le calcul : aucune mesure ne peut exister au-delà de
# l'instant réel, la période se contente d'inclure une fenêtre vide.
_CASH_FUTURE_TOLERANCE = timedelta(minutes=5)


def _validate_cash_period(from_date, to_date) -> tuple[datetime, datetime]:
    period_start = _to_naive_utc(from_date)
    period_end = _to_naive_utc(to_date)
    if period_start is None or period_end is None:
        raise AppError(code="cash_period_required", message="from_date et to_date sont obligatoires pour un calcul de caisse.", status_code=422)
    if period_start >= period_end:
        raise AppError(code="invalid_date_range", message="from_date doit être strictement antérieure à to_date.", status_code=422)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if period_end > now + _CASH_FUTURE_TOLERANCE:
        raise AppError(code="cash_period_in_future", message="La période demandée ne peut pas se terminer dans le futur.", status_code=422)
    return period_start, min(period_end, now)


def _operational_period_start(station: Station, requested_start: datetime, requested_end: datetime) -> datetime:
    """Début de la « journée d'exploitation » d'une station (audit Caisse
    P2 §E.1) : l'heure d'ouverture réelle de la station (`Station.openingTime`,
    déjà saisie mais jamais consommée par aucun calcul avant cet audit),
    plutôt que minuit civil. `is24h` retombe sur minuit (une station ouverte
    24h/24 n'a pas d'heure d'ouverture significative). Ne s'applique
    qu'aux requêtes courtes (≤ 24h, en pratique "aujourd'hui") : pour une
    plage plus longue, la notion de "journée d'exploitation" n'a pas de
    sens unique — on retombe alors silencieusement sur la borne demandée,
    jamais une heure inventée pour une période multi-jours."""
    if requested_end - requested_start > timedelta(hours=24):
        return requested_start
    if station.is24h:
        hour, minute = 0, 0
    else:
        try:
            hour, minute = (int(part) for part in station.openingTime.split(":")[:2])
        except (ValueError, AttributeError):
            hour, minute = 0, 0
    candidate = requested_end.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Ne jamais faire démarrer la journée d'exploitation avant la borne
    # explicitement demandée (ex. un `fromDate` personnalisé déjà postérieur
    # à l'heure d'ouverture) ni après la borne de fin.
    return max(requested_start, min(candidate, requested_end))


# Marge de grâce avant de considérer un jour définitivement clos et
# figeable en cache (audit Caisse P2 §E.3) — une mesure peut arriver en
# retard (page_caisse.md, cas K) ; on ne fige jamais un jour tant qu'elle a
# pu ne pas être encore reçue.
_CASH_CACHE_SETTLE_DELAY = timedelta(hours=6)


def _split_into_daily_buckets(period_start: datetime, period_end: datetime) -> list[tuple[datetime, datetime]]:
    """Découpe une période en tranches calées sur minuit civil — seules les
    tranches de 24h pleines qui en résultent sont éligibles au cache
    (audit Caisse P2 §E.3) ; les bords partiels (début/fin de période non
    alignés sur minuit) sont toujours recalculés en direct."""
    buckets: list[tuple[datetime, datetime]] = []
    cursor = period_start
    while cursor < period_end:
        next_midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min)
        bucket_end = min(next_midnight, period_end)
        buckets.append((cursor, bucket_end))
        cursor = bucket_end
    return buckets


def _tank_cash_summary_fields(result: dict) -> dict:
    """Ne garde que les champs de synthèse d'un résultat `_compute_tank_cash`
    (jamais les segments) — c'est tout ce dont les vues réseau/station ont
    besoin, et tout ce que le cache par jour peut légitimement porter."""
    return {
        "volumeSoldLiters": result["volumeSoldLiters"],
        "volumeNotCalculableReason": result["volumeNotCalculableReason"],
        "monetaryValue": result["monetaryValue"],
        "currencyCode": result["currencyCode"],
        "monetaryValueNotCalculableReason": result["monetaryValueNotCalculableReason"],
        "confidence": result["confidence"],
    }


async def _get_or_compute_tank_cash_for_day(
    db: AsyncSession, tank: Tank, day_start: datetime, day_end: datetime, price_context: _CashPriceContext | None = None
) -> dict:
    """Un jour calendaire plein (minuit à minuit) : sert le cache
    `TankCashDailyAggregate` si le jour est clos depuis au moins
    `_CASH_CACHE_SETTLE_DELAY`, sinon calcule en direct et met en cache
    pour la prochaine fois (jamais avant, cf. cas K)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settled = day_end <= now - _CASH_CACHE_SETTLE_DELAY
    cash_date = day_start.date()

    if settled:
        cached_result = await db.execute(
            select(TankCashDailyAggregate).where(TankCashDailyAggregate.tankId == tank.id, TankCashDailyAggregate.cashDate == cash_date)
        )
        row = cached_result.scalar_one_or_none()
        if row is not None:
            return {
                "volumeSoldLiters": float(row.volumeSoldLiters) if row.volumeSoldLiters is not None else None,
                "volumeNotCalculableReason": row.volumeNotCalculableReason,
                "monetaryValue": float(row.monetaryValue) if row.monetaryValue is not None else None,
                "currencyCode": row.currencyCode,
                "monetaryValueNotCalculableReason": row.monetaryValueNotCalculableReason,
                "confidence": row.confidence,
            }

    result = _tank_cash_summary_fields(await _compute_tank_cash(db, tank, day_start, day_end, price_context))

    if settled:
        db.add(
            TankCashDailyAggregate(
                tankId=tank.id,
                cashDate=cash_date,
                volumeSoldLiters=result["volumeSoldLiters"],
                volumeNotCalculableReason=result["volumeNotCalculableReason"],
                monetaryValue=result["monetaryValue"],
                currencyCode=result["currencyCode"],
                monetaryValueNotCalculableReason=result["monetaryValueNotCalculableReason"],
                confidence=result["confidence"],
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # Course avec une autre requête ayant mis en cache ce même jour
            # entre-temps — sans conséquence, le résultat déjà calculé reste
            # correct, on ne fait que renoncer à l'écrire une seconde fois.
            await db.rollback()

    return result


def _merge_tank_cash_summaries(results: list[dict]) -> dict:
    """Combine plusieurs résultats de synthèse (un par tranche de période,
    audit Caisse P2 §E.3) : le volume se somme toujours, le montant
    uniquement si toutes les tranches sont calculables dans la même devise
    (jamais une somme entre devises différentes, jamais un montant partiel
    fait passer pour complet), la confiance retient toujours la pire des
    tranches.

    Distinction importante : une tranche « insufficient_data » (aucune
    mesure du tout ce jour-là, ex. avant le début réel de la télémétrie)
    est simplement exclue de la somme, exactement comme le volume — elle
    ne bloque jamais le total des autres jours qui, eux, ont une vraie
    donnée. Seule une vraie question de prix (aucun prix applicable,
    devises mélangées, tarification incomplète) bloque le montant total :
    on ne masque jamais un problème de prix en le traitant comme une
    simple absence de données."""
    _BLOCKING_MONETARY_REASONS = {"no_applicable_price", "mixed_currencies", "incomplete_pricing"}

    total_volume: float | None = None
    total_monetary: float | None = None
    currency_code: str | None = None
    volume_reason: str | None = None
    monetary_reason: str | None = None
    monetary_blocked = False
    confidence = "reliable"

    for result in results:
        confidence = _worse_cash_confidence(confidence, result["confidence"])
        if result["volumeSoldLiters"] is None:
            volume_reason = volume_reason or result["volumeNotCalculableReason"]
        else:
            total_volume = (total_volume or 0.0) + result["volumeSoldLiters"]

        if result["monetaryValue"] is None:
            reason = result["monetaryValueNotCalculableReason"]
            if reason in _BLOCKING_MONETARY_REASONS:
                monetary_reason = reason
                monetary_blocked = True
                total_monetary = None
            elif not monetary_blocked:
                monetary_reason = monetary_reason or reason
        elif not monetary_blocked:
            # Un montant à 0 sans devise associée (rien vendu ce jour-là,
            # aucun segment à valoriser) est une contribution neutre —
            # jamais comparée comme un désaccord de devise avec les autres
            # tranches (sinon un jour parfaitement calme bloquerait à tort
            # tout le total en « mixed_currencies »).
            if result["currencyCode"] is None:
                total_monetary = (total_monetary or 0.0) + result["monetaryValue"]
            elif currency_code is not None and result["currencyCode"] != currency_code:
                monetary_reason = "mixed_currencies"
                monetary_blocked = True
                total_monetary = None
            else:
                currency_code = result["currencyCode"]
                total_monetary = (total_monetary or 0.0) + result["monetaryValue"]

    return {
        "volumeSoldLiters": total_volume,
        "volumeNotCalculableReason": None if total_volume is not None else (volume_reason or "insufficient_data"),
        "monetaryValue": total_monetary,
        "currencyCode": currency_code if total_monetary is not None else None,
        "monetaryValueNotCalculableReason": None if total_monetary is not None else (monetary_reason or "insufficient_data"),
        "confidence": confidence,
    }


async def _compute_tank_cash_over_period(
    db: AsyncSession, tank: Tank, period_start: datetime, period_end: datetime, price_context: _CashPriceContext | None = None
) -> dict:
    """Point d'entrée pour les vues réseau/station (jamais pour la
    traçabilité par cuve, qui a besoin des segments et recalcule toujours
    en direct sur toute la période demandée). Sur une période courte
    (≤ 24h : "aujourd'hui", "hier", journée d'exploitation...), calcule en
    direct sans découpage — inutile en dessous d'un jour. Sur une période
    plus longue (7/30 jours), découpe en jours calendaires et sert le
    cache par jour clos (audit Caisse P2 §E.3).

    `price_context` (audit performance 2026-09-11) : propagé tel quel à
    chaque jour — construit une seule fois par l'appelant réseau/station,
    jamais recalculé ici."""
    if period_end - period_start <= timedelta(hours=24):
        return _tank_cash_summary_fields(await _compute_tank_cash(db, tank, period_start, period_end, price_context))

    buckets = _split_into_daily_buckets(period_start, period_end)
    results = []
    for bucket_start, bucket_end in buckets:
        if bucket_end - bucket_start >= timedelta(hours=23, minutes=59):
            results.append(await _get_or_compute_tank_cash_for_day(db, tank, bucket_start, bucket_end, price_context))
        else:
            results.append(_tank_cash_summary_fields(await _compute_tank_cash(db, tank, bucket_start, bucket_end, price_context)))
    return _merge_tank_cash_summaries(results)


async def get_tank_cash(
    db: AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID, from_date, to_date, mode: str = "calendar"
) -> TankCashResponse:
    period_start, period_end = _validate_cash_period(from_date, to_date)
    tank = await get_tank(db, organization_id, tank_id)
    fuel_product = await get_fuel_product(db, organization_id, tank.fuelProductId)
    effective_start = period_start
    if mode == "operational":
        station = await get_station(db, organization_id, tank.stationId)
        effective_start = _operational_period_start(station, period_start, period_end)
    result = await _compute_tank_cash(db, tank, effective_start, period_end)
    return TankCashResponse(
        periodStart=effective_start,
        periodEnd=period_end,
        displayName=tank.displayName,
        fuelProductName=fuel_product.name,
        **result,
    )


async def get_station_cash_detail(
    db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID, from_date, to_date, mode: str = "calendar"
) -> StationCashDetailResponse:
    period_start, period_end = _validate_cash_period(from_date, to_date)
    station = await get_station(db, organization_id, station_id)
    effective_start = _operational_period_start(station, period_start, period_end) if mode == "operational" else period_start

    tanks_result = await db.execute(select(Tank).where(Tank.stationId == station.id, Tank.active.is_(True)))
    tanks = tanks_result.scalars().all()

    fuel_products_result = await db.execute(select(FuelProduct).where(FuelProduct.organizationId == organization_id))
    fuel_products_by_id = {fp.id: fp for fp in fuel_products_result.scalars().all()}

    price_contexts = await _build_cash_price_contexts(db, tanks)

    per_product: dict[uuid.UUID, dict] = {}
    station_volume = 0.0
    station_monetary = 0.0
    station_currency: str | None = None
    station_incomplete = False
    station_confidence = "reliable"

    for tank in tanks:
        cash = await _compute_tank_cash_over_period(db, tank, effective_start, period_end, price_contexts.get(tank.id))
        entry = per_product.setdefault(
            tank.fuelProductId, {"tanks": [], "volume": 0.0, "monetary": 0.0, "currencies": set(), "incomplete": False, "confidence": "reliable"}
        )
        entry["tanks"].append(
            TankCashSummaryLine(
                tankId=tank.id,
                displayName=tank.displayName,
                fuelProductId=tank.fuelProductId,
                fuelProductName=fuel_products_by_id[tank.fuelProductId].name if tank.fuelProductId in fuel_products_by_id else "?",
                volumeSoldLiters=cash["volumeSoldLiters"],
                volumeNotCalculableReason=cash["volumeNotCalculableReason"],
                monetaryValue=cash["monetaryValue"],
                currencyCode=cash["currencyCode"],
                monetaryValueNotCalculableReason=cash["monetaryValueNotCalculableReason"],
                confidence=cash["confidence"],
            )
        )
        entry["confidence"] = _worse_cash_confidence(entry["confidence"], cash["confidence"])
        station_confidence = _worse_cash_confidence(station_confidence, cash["confidence"])
        if cash["volumeSoldLiters"] is not None:
            entry["volume"] += cash["volumeSoldLiters"]
            station_volume += cash["volumeSoldLiters"]
        if cash["monetaryValue"] is None:
            entry["incomplete"] = True
            station_incomplete = True
        else:
            entry["monetary"] += cash["monetaryValue"]
            station_monetary += cash["monetaryValue"]
            if cash["currencyCode"] is not None:
                entry["currencies"].add(cash["currencyCode"])
                if station_currency is not None and cash["currencyCode"] != station_currency:
                    station_incomplete = True
                station_currency = cash["currencyCode"]

    products: list[ProductCashLine] = []
    for fuel_product_id, entry in per_product.items():
        if entry["incomplete"]:
            p_monetary, p_currency, p_reason = None, None, "incomplete_pricing"
        elif len(entry["currencies"]) > 1:
            p_monetary, p_currency, p_reason = None, None, "mixed_currencies"
        elif len(entry["currencies"]) == 1:
            p_monetary, p_currency, p_reason = entry["monetary"], next(iter(entry["currencies"])), None
        else:
            p_monetary, p_currency, p_reason = None, None, "no_applicable_price"
        products.append(
            ProductCashLine(
                fuelProductId=fuel_product_id,
                fuelProductName=fuel_products_by_id[fuel_product_id].name if fuel_product_id in fuel_products_by_id else "?",
                tankCount=len(entry["tanks"]),
                volumeSoldLiters=entry["volume"],
                monetaryValue=p_monetary,
                currencyCode=p_currency,
                monetaryValueNotCalculableReason=p_reason,
                confidence=entry["confidence"],
                tanks=entry["tanks"],
            )
        )

    station_monetary_final = None if (station_incomplete or station_currency is None) else station_monetary
    return StationCashDetailResponse(
        stationId=station.id,
        stationName=station.name,
        periodStart=effective_start,
        periodEnd=period_end,
        tankCount=len(tanks),
        volumeSoldLiters=station_volume,
        monetaryValue=station_monetary_final,
        currencyCode=station_currency if station_monetary_final is not None else None,
        monetaryValueNotCalculableReason=None if station_monetary_final is not None else ("mixed_currencies" if station_currency and station_incomplete else "incomplete_pricing" if station_incomplete else "no_applicable_price"),
        confidence=station_confidence,
        products=products,
    )


async def get_network_cash_summary(
    db: AsyncSession, organization_id: uuid.UUID, from_date, to_date, mode: str = "calendar"
) -> NetworkCashSummaryResponse:
    """Caisse réseau agrégée par devise (page_caisse.md §H) — jamais une
    somme entre devises différentes. Vue résumée par station uniquement :
    le détail produit/cuve se charge au clic via get_station_cash_detail
    (page_caisse.md §31, pas tout chargé d'un coup). `mode="operational"`
    (audit Caisse P2 §E.1) fait démarrer la période de chaque station à sa
    propre heure d'ouverture plutôt qu'à minuit civil — chaque station
    garde donc sa propre borne de départ, jamais une heure unique imposée
    à tout le réseau."""
    period_start, period_end = _validate_cash_period(from_date, to_date)

    stations_result = await db.execute(
        select(Station).where(Station.organizationId == organization_id, Station.status == "active")
    )
    stations = stations_result.scalars().all()
    station_ids = [s.id for s in stations]

    # Un seul aller-retour pour les cuves de TOUTES les stations, plutôt
    # qu'une requête par station (audit performance 2026-09-11) — regroupées
    # ensuite en mémoire par stationId.
    tanks_by_station: dict[uuid.UUID, list[Tank]] = {}
    all_tanks: list[Tank] = []
    if station_ids:
        all_tanks_result = await db.execute(select(Tank).where(Tank.stationId.in_(station_ids), Tank.active.is_(True)))
        all_tanks = list(all_tanks_result.scalars().all())
        for tank in all_tanks:
            tanks_by_station.setdefault(tank.stationId, []).append(tank)

    # Prix réseau par défaut + devise de station, précalculés une seule fois
    # pour toutes les cuves (audit performance 2026-09-11) — voir
    # `_build_cash_price_contexts` : élimine la résolution de prix/devise
    # répétée à chaque frontière de segment de vente, qui dominait le temps
    # de calcul de la caisse (mesuré jusqu'à ~50s sur 7 jours).
    price_contexts = await _build_cash_price_contexts(db, all_tanks)

    # Dernière mesure connue (`lastValueAt`) pour toutes les cuves en un
    # seul aller-retour, au lieu d'un `_get_active_registry_entry` par cuve.
    last_measurement_by_tank: dict[uuid.UUID, datetime] = {}
    if all_tanks:
        registry_result = await db.execute(
            select(TankSensorMapping.tankId, HolykellDeviceRegistry.lastValueAt)
            .join(HolykellDeviceRegistry, HolykellDeviceRegistry.hkSensorId == TankSensorMapping.hkSensorId)
            .where(
                TankSensorMapping.tankId.in_([t.id for t in all_tanks]),
                TankSensorMapping.measurementType == "product_level",
                TankSensorMapping.active.is_(True),
            )
        )
        for tank_id, last_value_at in registry_result.all():
            if last_value_at is not None:
                last_measurement_by_tank[tank_id] = last_value_at

    currency_blocks: dict[str, dict] = {}
    product_totals: dict[uuid.UUID, dict] = {}
    station_lines: list[StationCashSummaryLine] = []
    stations_with_data = 0
    incomplete_pricing_stations = 0
    product_ids: set[uuid.UUID] = set()
    last_measurement_at: datetime | None = None

    for station in stations:
        tanks = tanks_by_station.get(station.id, [])
        if not tanks:
            continue

        station_volume = 0.0
        station_monetary = 0.0
        station_currency: str | None = None
        station_incomplete = False
        station_confidence = "reliable"
        station_has_data = False
        station_effective_start = _operational_period_start(station, period_start, period_end) if mode == "operational" else period_start

        for tank in tanks:
            cash = await _compute_tank_cash_over_period(db, tank, station_effective_start, period_end, price_contexts.get(tank.id))
            product_ids.add(tank.fuelProductId)
            station_confidence = _worse_cash_confidence(station_confidence, cash["confidence"])
            tank_last_value_at = last_measurement_by_tank.get(tank.id)
            if tank_last_value_at is not None:
                if last_measurement_at is None or tank_last_value_at > last_measurement_at:
                    last_measurement_at = tank_last_value_at
            if cash["volumeSoldLiters"] is not None:
                station_volume += cash["volumeSoldLiters"]
                station_has_data = True
            if cash["monetaryValue"] is None:
                station_incomplete = True
            else:
                station_monetary += cash["monetaryValue"]
                if station_currency is not None and cash["currencyCode"] != station_currency:
                    station_incomplete = True
                station_currency = cash["currencyCode"]

            product_entry = product_totals.setdefault(
                tank.fuelProductId,
                {"tankIds": set(), "stationIds": set(), "volume": 0.0, "monetary": 0.0, "currencies": set(), "incomplete": False, "confidence": "reliable", "stations": {}},
            )
            product_entry["tankIds"].add(tank.id)
            product_entry["stationIds"].add(station.id)
            product_entry["confidence"] = _worse_cash_confidence(product_entry["confidence"], cash["confidence"])

            product_station_entry = product_entry["stations"].setdefault(
                station.id,
                {"stationName": station.name, "tankCount": 0, "volume": 0.0, "monetary": 0.0, "currencies": set(), "incomplete": False, "confidence": "reliable"},
            )
            product_station_entry["tankCount"] += 1
            product_station_entry["confidence"] = _worse_cash_confidence(product_station_entry["confidence"], cash["confidence"])
            if cash["volumeSoldLiters"] is not None:
                product_station_entry["volume"] += cash["volumeSoldLiters"]
            if cash["monetaryValue"] is None:
                product_station_entry["incomplete"] = True
            else:
                product_station_entry["monetary"] += cash["monetaryValue"]
                if cash["currencyCode"] is not None:
                    product_station_entry["currencies"].add(cash["currencyCode"])

            if cash["volumeSoldLiters"] is not None:
                product_entry["volume"] += cash["volumeSoldLiters"]
            if cash["monetaryValue"] is None:
                product_entry["incomplete"] = True
            else:
                product_entry["monetary"] += cash["monetaryValue"]
                if cash["currencyCode"] is not None:
                    product_entry["currencies"].add(cash["currencyCode"])

        if station_has_data:
            stations_with_data += 1
        if station_incomplete:
            incomplete_pricing_stations += 1

        block_currency = station_currency if (station_currency is not None and not station_incomplete) else None
        line = StationCashSummaryLine(
            stationId=station.id,
            stationName=station.name,
            tankCount=len(tanks),
            volumeSoldLiters=station_volume,
            monetaryValue=station_monetary if block_currency is not None else None,
            currencyCode=block_currency,
            monetaryValueNotCalculableReason=None if block_currency is not None else ("mixed_currencies" if station_incomplete and station_currency else "incomplete_pricing" if station_incomplete else "no_applicable_price"),
            confidence=station_confidence,
        )

        station_lines.append(line)

        key = block_currency or "__uncalculable__"
        block = currency_blocks.setdefault(key, {"currencyCode": block_currency, "monetary": 0.0, "volume": 0.0, "stations": []})
        block["stations"].append(line)
        block["volume"] += station_volume
        if block_currency is not None:
            block["monetary"] += station_monetary

    blocks = [
        CurrencyCashBlock(
            currencyCode=block["currencyCode"],
            monetaryValue=block["monetary"],
            volumeSoldLiters=block["volume"],
            stationCount=len(block["stations"]),
            stations=block["stations"],
        )
        for key, block in currency_blocks.items()
        if block["currencyCode"] is not None
    ]
    uncalculable_block = currency_blocks.get("__uncalculable__")

    fuel_products_result = await db.execute(select(FuelProduct).where(FuelProduct.organizationId == organization_id))
    fuel_products_by_id = {fp.id: fp for fp in fuel_products_result.scalars().all()}

    product_blocks: list[NetworkProductCashLine] = []
    for fuel_product_id, entry in product_totals.items():
        if entry["incomplete"]:
            p_monetary, p_currency, p_reason = None, None, "incomplete_pricing"
        elif len(entry["currencies"]) > 1:
            p_monetary, p_currency, p_reason = None, None, "mixed_currencies"
        elif len(entry["currencies"]) == 1:
            p_monetary, p_currency, p_reason = entry["monetary"], next(iter(entry["currencies"])), None
        else:
            p_monetary, p_currency, p_reason = None, None, "no_applicable_price"
        fuel_product = fuel_products_by_id.get(fuel_product_id)

        product_station_lines: list[StationCashSummaryLine] = []
        for station_id, station_entry in entry["stations"].items():
            if station_entry["incomplete"]:
                s_monetary, s_currency, s_reason = None, None, "incomplete_pricing"
            elif len(station_entry["currencies"]) > 1:
                s_monetary, s_currency, s_reason = None, None, "mixed_currencies"
            elif len(station_entry["currencies"]) == 1:
                s_monetary, s_currency, s_reason = station_entry["monetary"], next(iter(station_entry["currencies"])), None
            else:
                s_monetary, s_currency, s_reason = None, None, "no_applicable_price"
            product_station_lines.append(
                StationCashSummaryLine(
                    stationId=station_id,
                    stationName=station_entry["stationName"],
                    tankCount=station_entry["tankCount"],
                    volumeSoldLiters=station_entry["volume"],
                    monetaryValue=s_monetary,
                    currencyCode=s_currency,
                    monetaryValueNotCalculableReason=s_reason,
                    confidence=station_entry["confidence"],
                )
            )

        product_blocks.append(
            NetworkProductCashLine(
                fuelProductId=fuel_product_id,
                fuelProductName=fuel_product.name if fuel_product else "?",
                displayColor=fuel_product.displayColor if fuel_product else None,
                tankCount=len(entry["tankIds"]),
                stationCount=len(entry["stationIds"]),
                volumeSoldLiters=entry["volume"],
                monetaryValue=p_monetary,
                currencyCode=p_currency,
                monetaryValueNotCalculableReason=p_reason,
                confidence=entry["confidence"],
                stations=product_station_lines,
            )
        )

    return NetworkCashSummaryResponse(
        periodStart=period_start,
        periodEnd=period_end,
        currencyBlocks=blocks,
        productBlocks=product_blocks,
        stationLines=station_lines,
        volumeSoldLitersTotal=sum(b.volumeSoldLiters for b in blocks) + (uncalculable_block["volume"] if uncalculable_block else 0.0),
        stationsWithDataCount=stations_with_data,
        stationsTotalCount=len(stations),
        productCount=len(product_ids),
        incompletePricingStationCount=incomplete_pricing_stations,
        lastMeasurementAt=last_measurement_at,
    )


# ================================================================
# Couche déclarative (processus-double-sources-verite, Phase 5-8) — Bloc 1.
# Chaque type reste sa propre entité et son propre schéma (Phase 5 §1), mais
# la forme de la logique est identique pour les 6 types : résoudre la
# station, vérifier la portée scopée (même mécanisme que PRICE_HISTORY_CREATE,
# Phase 4 §4 de refonte-configuration-zylo-liquid.md), puis soit insérer une
# nouvelle ligne (jamais une réécriture), soit modifier en place tant que
# `lifecycleStatus = 'declared'` (Phase 5 §2-3), soit verrouiller
# définitivement. Factorisée ici pour ne pas dupliquer six fois la même
# logique de portée/pagination — chaque type garde son schéma dédié.
# ================================================================


async def _check_declaration_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station: Station, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code, "station", station.id)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)


async def _get_declaration_or_404(db: AsyncSession, model_cls: type[DeclarationMixin], organization_id: uuid.UUID, declaration_id: uuid.UUID):
    instance = await db.get(model_cls, declaration_id)
    if instance is not None:
        station = await db.get(Station, instance.stationId)
        if station is not None and station.organizationId == organization_id:
            return instance
    raise AppError(code="declaration_not_found", message="Déclaration introuvable.", status_code=404)


async def _list_declarations(
    db: AsyncSession,
    model_cls: type[DeclarationMixin],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    read_permission: str,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    restrict_to_own_author_unless_permission: str | None = None,
):
    """`restrict_to_own_author_unless_permission` — reprend le comportement
    exact du prototype validé pour le pompiste (`prototype.html`,
    `dashPompiste()`/filtre `estPompiste` : « Ce rôle... limite le pompiste
    à ses propres ventes et à son shift ») : un utilisateur qui ne possède
    PAS le code de permission donné (typiquement `STATION_READ`, qui
    conditionne toute vue de pilotage station selon la matrice rôles × vues
    du prototype) ne voit que les déclarations dont il est lui-même
    l'auteur, jamais celles de ses collègues de la même station."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, read_permission, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {read_permission}.", status_code=403)
    if station_id is not None and not sees_all and station_id not in visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {read_permission}.", status_code=403)

    stmt = select(model_cls).join(Station, Station.id == model_cls.stationId).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(model_cls.stationId.in_(visible_station_ids))
    if station_id is not None:
        stmt = stmt.where(model_cls.stationId == station_id)
    if restrict_to_own_author_unless_permission is not None:
        has_broad_view = await user_has_permission(db, actor_user_id, organization_id, restrict_to_own_author_unless_permission)
        if not has_broad_view:
            stmt = stmt.where(model_cls.authorUserId == actor_user_id)
    stmt = stmt.order_by(model_cls.eventAt.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    return list(result.scalars().all()), total or 0


async def _lock_declaration(db: AsyncSession, model_cls: type[DeclarationMixin], organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID):
    """Passage direct à `locked` (Phase 5 §3 : aucun état intermédiaire
    "validée mais encore modifiable"). Jamais l'inverse — un déverrouillage
    n'existe pas comme opération, seule une nouvelle déclaration corrective
    (`correctsDeclarationId`) permet de rectifier une déclaration verrouillée."""
    instance = await _get_declaration_or_404(db, model_cls, organization_id, declaration_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, await db.get(Station, instance.stationId), DECLARATION_LOCK)
    if instance.lifecycleStatus == "locked":
        raise AppError(code="declaration_already_locked", message="Cette déclaration est déjà verrouillée.", status_code=409)
    instance.lifecycleStatus = "locked"
    await db.commit()
    await db.refresh(instance)
    return instance


async def _update_declaration_in_place(
    db: AsyncSession, model_cls: type[DeclarationMixin], organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, updates: dict
):
    """Modification en place, réservée à l'auteur et au seul état
    'declared' (Phase 5 §2-3) — jamais après verrouillage, jamais un autre
    utilisateur que l'auteur (une correction par un tiers passe par le
    verrouillage puis une nouvelle déclaration corrective, pas cette voie)."""
    instance = await _get_declaration_or_404(db, model_cls, organization_id, declaration_id)
    if instance.authorUserId != actor_user_id:
        raise AppError(code="permission_denied", message="Seul l'auteur peut modifier sa propre déclaration.", status_code=403)
    if instance.lifecycleStatus != "declared":
        raise AppError(code="declaration_locked", message="Cette déclaration est verrouillée — une correction doit être une nouvelle déclaration.", status_code=409)
    for field, value in updates.items():
        if value is not None:
            setattr(instance, field, value)
    await db.commit()
    await db.refresh(instance)
    return instance


async def _validate_delivery_header_links(
    db: AsyncSession, organization_id: uuid.UUID, supplier_id: uuid.UUID | None, truck_id: uuid.UUID | None, supplier_name: str | None,
) -> str | None:
    """Contrôles de cohérence des raccordements d'EN-TÊTE (fournisseur,
    camion) — communs à toute la visite, indépendants des lignes. Retourne
    le `supplierName` à stocker : le libellé fourni s'il existe, sinon le
    nom du fournisseur du référentiel — instantané documentaire (même rôle
    que `Payment.exchangeRateApplied`), jamais une seconde source de vérité
    pour le rapprochement (Phase 6)."""
    if supplier_id is not None:
        supplier = await _get_supplier_or_404(db, organization_id, supplier_id)
        if supplier_name is None:
            supplier_name = supplier.name
    if truck_id is not None:
        truck = await db.get(Truck, truck_id)
        if truck is None or truck.organizationId != organization_id:
            raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    return supplier_name


async def _validate_delivery_declaration_line(
    db: AsyncSession, organization_id: uuid.UUID, station: Station, tank_id: uuid.UUID,
    purchase_order_line_id: uuid.UUID | None, supplier_id: uuid.UUID | None, tolerate_received_order: bool = False,
) -> None:
    """Contrôles de cohérence d'UNE ligne de livraison (refonte 2026-09-17,
    scénario par scénario avec le commanditaire) :
      - la cuve appartient à la station de la déclaration ;
      - si une ligne de commande est indiquée (scénario E : optionnel, une
        livraison peut ne référencer aucune commande), elle concerne le même
        produit que la cuve visée (jamais stocké séparément — pas de double
        vérité) et n'est pas déjà 'received' — sauf `tolerate_received_order` :
        une correction CIBLÉE (scénario I) reproduit la livraison d'origine
        sur la même ligne de commande, même réceptionnée entre-temps, elle
        ne crée aucun volume nouveau, elle remplace la ligne corrigée ;
      - fournisseur cohérent avec celui de la commande quand les deux sont
        fournis."""
    tank = await get_tank(db, organization_id, tank_id)
    if tank.stationId != station.id:
        raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station de la livraison.", status_code=422)
    if purchase_order_line_id is not None:
        order_line = await db.get(PurchaseOrderLine, purchase_order_line_id)
        if order_line is None:
            raise AppError(code="purchase_order_line_not_found", message="Ligne de commande introuvable.", status_code=404)
        purchase_order = await _get_purchase_order_or_404(db, organization_id, order_line.purchaseOrderId)
        if purchase_order.stationId != station.id:
            raise AppError(code="purchase_order_station_mismatch", message="Cette commande d'approvisionnement ne concerne pas la station de la réception.", status_code=422)
        if order_line.status == "received" and not tolerate_received_order:
            raise AppError(code="purchase_order_line_received", message="Cette ligne de commande est déjà entièrement réceptionnée.", status_code=409)
        if order_line.fuelProductId != tank.fuelProductId:
            raise AppError(code="purchase_order_product_mismatch", message="Le produit de la ligne de commande ne correspond pas à celui de la cuve livrée.", status_code=422)
        if supplier_id is not None and supplier_id != purchase_order.supplierId:
            raise AppError(code="purchase_order_supplier_mismatch", message="Le fournisseur indiqué ne correspond pas à celui de la commande.", status_code=422)


async def create_delivery_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateDeliveryDeclarationRequest) -> DeliveryDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, DELIVERY_DECLARATION_CREATE)
    supplier_name = await _validate_delivery_header_links(db, organization_id, data.supplierId, data.truckId, data.supplierName)
    for line in data.lines:
        await _validate_delivery_declaration_line(db, organization_id, station, line.tankId, line.purchaseOrderLineId, data.supplierId)

    instance = DeliveryDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        supplierName=supplier_name,
        supplierId=data.supplierId,
        truckId=data.truckId,
        deliveryNoteReference=data.deliveryNoteReference,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.flush()
    lines: list[DeliveryDeclarationLine] = []
    for line in data.lines:
        declaration_line = DeliveryDeclarationLine(
            declarationId=instance.id, tankId=line.tankId, purchaseOrderLineId=line.purchaseOrderLineId, volumeLiters=line.volumeLiters,
        )
        db.add(declaration_line)
        lines.append(declaration_line)
    await db.commit()
    await db.refresh(instance)

    # Déclenchement automatique du rapprochement (mission « flux de
    # livraison station », point 3 : « dès qu'une livraison est déclarée »)
    # — best-effort, ne doit jamais faire échouer la déclaration elle-même
    # si le rapprochement rencontre un problème imprévu. Une ligne à la fois
    # (refonte 2026-09-17) : chaque cuve se rapproche de sa propre détection.
    for line in lines:
        try:
            await db.refresh(line)
            await _evaluate_delivery_declaration_line_reconciliation_core(db, instance, line)
        except Exception:
            await db.rollback()
    try:
        await _sweep_stale_pending_delivery_declarations(db, station.id)
    except Exception:
        await db.rollback()

    return await _to_delivery_declaration_response(db, instance)


async def _load_delivery_declaration_lines(db: AsyncSession, declaration_id: uuid.UUID) -> list[DeliveryDeclarationLine]:
    result = await db.execute(select(DeliveryDeclarationLine).where(DeliveryDeclarationLine.declarationId == declaration_id).order_by(DeliveryDeclarationLine.createdAt.asc()))
    return list(result.scalars().all())


async def _to_delivery_declaration_response(db: AsyncSession, declaration: DeliveryDeclaration) -> DeliveryDeclarationResponse:
    lines = await _load_delivery_declaration_lines(db, declaration.id)
    response = DeliveryDeclarationResponse.model_validate(declaration)
    response.lines = [DeliveryDeclarationLineResponse.model_validate(l) for l in lines]
    return response


async def update_delivery_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateDeliveryDeclarationRequest) -> DeliveryDeclarationResponse:
    """En-tête uniquement (refonte 2026-09-17) — les lignes ne se modifient
    jamais en place, voir `UpdateDeliveryDeclarationRequest`."""
    updates = data.model_dump(exclude_unset=True)
    if "eventAt" in updates and updates["eventAt"] is not None:
        updates["eventAt"] = _to_naive_utc(updates["eventAt"])

    # Gardes identiques à `_update_declaration_in_place` (auteur, état
    # 'declared') dupliquées ici à dessein : la validation des raccordements
    # fournisseur/camion doit s'exécuter AVANT l'application des mises à
    # jour et sur les valeurs finales — le générique ne peut pas la porter.
    # `supplierId`/`truckId` sont en outre les seuls champs où un null
    # EXPLICITE décroche la ligne du référentiel : pour eux, contrairement
    # aux autres champs, la valeur None est bien appliquée (les autres
    # conservent le comportement hérité : None ignoré).
    instance = await _get_declaration_or_404(db, DeliveryDeclaration, organization_id, declaration_id)
    if instance.authorUserId != actor_user_id:
        raise AppError(code="permission_denied", message="Seul l'auteur peut modifier sa propre déclaration.", status_code=403)
    if instance.lifecycleStatus != "declared":
        raise AppError(code="declaration_locked", message="Cette déclaration est verrouillée — une correction doit être une nouvelle déclaration.", status_code=409)
    if "supplierId" in updates and updates["supplierId"] is not None and "supplierName" not in updates:
        # Changement de fournisseur référentiel sans libellé explicite :
        # re-synchroniser l'instantané documentaire sur le nouveau nom.
        updates["supplierName"] = None
    updates["supplierName"] = await _validate_delivery_header_links(
        db, organization_id, updates.get("supplierId", instance.supplierId), updates.get("truckId", instance.truckId), updates.get("supplierName", instance.supplierName),
    )
    for field, value in updates.items():
        if field in ("supplierId", "truckId"):
            setattr(instance, field, value)
        elif value is not None:
            setattr(instance, field, value)
    await db.commit()
    await db.refresh(instance)
    return await _to_delivery_declaration_response(db, instance)


async def list_delivery_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, DeliveryDeclaration, organization_id, actor_user_id, DELIVERY_DECLARATION_READ, pagination, station_id)
    data = [await _to_delivery_declaration_response(db, r) for r in rows]
    return Page(data=data, meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_delivery_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> DeliveryDeclarationResponse:
    instance = await _lock_declaration(db, DeliveryDeclaration, organization_id, actor_user_id, declaration_id)
    # Le verrouillage est l'acte définitif d'une réception : c'est le seul
    # moment où une ligne de commande rattachée peut passer à 'received'
    # (jamais à la création — une déclaration 'declared' reste révisable).
    # Une ligne de déclaration à la fois (refonte 2026-09-17) : chacune peut
    # référencer une ligne de commande différente (scénario C, multi-produits).
    lines = await _load_delivery_declaration_lines(db, instance.id)
    for line in lines:
        if line.purchaseOrderLineId is not None:
            await _receive_purchase_order_line_if_complete(db, line.purchaseOrderLineId)
    return await _to_delivery_declaration_response(db, instance)


async def correct_delivery_declaration_lines(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CorrectDeliveryDeclarationLinesRequest) -> DeliveryDeclarationResponse:
    """Correction CIBLÉE d'une ou plusieurs lignes (scénario I, option
    validée avec le commanditaire) : crée une nouvelle déclaration ne
    portant QUE la/les ligne(s) corrigées — jamais `correctsDeclarationId`
    (qui remplacerait toute la déclaration d'origine, l'autre option
    explicitement écartée) : les lignes non concernées de l'originale
    restent valables telles quelles, seules celles référencées par
    `correctsLineId` sont supplantées (exclues des sommes de réception,
    voir `_receive_purchase_order_line_if_complete`)."""
    original = await _get_declaration_or_404(db, DeliveryDeclaration, organization_id, data.declarationId)
    station = await db.get(Station, original.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, DELIVERY_DECLARATION_CREATE)

    final_supplier_id = data.supplierId if data.supplierId is not None else original.supplierId
    final_truck_id = data.truckId if data.truckId is not None else original.truckId
    supplier_name = await _validate_delivery_header_links(db, organization_id, final_supplier_id, final_truck_id, data.supplierName)

    original_lines_by_id = {l.id: l for l in await _load_delivery_declaration_lines(db, original.id)}
    for line_data in data.lines:
        corrected_line = original_lines_by_id.get(line_data.correctsLineId)
        if corrected_line is None:
            raise AppError(code="delivery_declaration_line_not_found", message="Ligne à corriger introuvable sur cette déclaration.", status_code=404)
        # Une correction reproduit la livraison d'origine sur la même ligne
        # de commande, même réceptionnée entre-temps — elle ne crée aucun
        # volume nouveau, elle remplace la ligne corrigée.
        tolerate_received_order = line_data.purchaseOrderLineId is not None and line_data.purchaseOrderLineId == corrected_line.purchaseOrderLineId
        await _validate_delivery_declaration_line(db, organization_id, station, line_data.tankId, line_data.purchaseOrderLineId, final_supplier_id, tolerate_received_order)

    instance = DeliveryDeclaration(
        stationId=original.stationId,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt) if data.eventAt is not None else original.eventAt,
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        supplierName=supplier_name if supplier_name is not None else original.supplierName,
        supplierId=final_supplier_id,
        truckId=final_truck_id,
        deliveryNoteReference=data.deliveryNoteReference if data.deliveryNoteReference is not None else original.deliveryNoteReference,
        changeReason=data.changeReason,
        correctsDeclarationId=None,
    )
    db.add(instance)
    await db.flush()
    new_lines: list[DeliveryDeclarationLine] = []
    for line_data in data.lines:
        new_line = DeliveryDeclarationLine(
            declarationId=instance.id, tankId=line_data.tankId, purchaseOrderLineId=line_data.purchaseOrderLineId,
            volumeLiters=line_data.volumeLiters, correctsLineId=line_data.correctsLineId,
        )
        db.add(new_line)
        new_lines.append(new_line)
    await db.commit()

    for line in new_lines:
        try:
            await db.refresh(line)
            await _evaluate_delivery_declaration_line_reconciliation_core(db, instance, line)
        except Exception:
            await db.rollback()
    # La correction elle-même reste 'declared' (comme toute nouvelle
    # déclaration) — le recalcul du statut de commande n'a lieu qu'au
    # verrouillage (voir `lock_delivery_declaration`), pas ici.

    return await _to_delivery_declaration_response(db, instance)


async def create_shift_cash_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateShiftCashDeclarationRequest) -> ShiftCashDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, SHIFT_CASH_DECLARATION_CREATE)
    tank = await get_tank(db, organization_id, data.tankId)
    if tank.stationId != station.id:
        raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station indiquée.", status_code=422)
    currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
    if currency_result.scalar_one_or_none() is None:
        raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
    instance = ShiftCashDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        tankId=data.tankId,
        shiftStart=_to_naive_utc(data.shiftStart),
        shiftEnd=_to_naive_utc(data.shiftEnd),
        openingReadingMm=data.openingReadingMm,
        closingReadingMm=data.closingReadingMm,
        declaredCashAmount=data.declaredCashAmount,
        currencyId=data.currencyId,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return ShiftCashDeclarationResponse.model_validate(instance)


async def update_shift_cash_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateShiftCashDeclarationRequest) -> ShiftCashDeclarationResponse:
    updates = data.model_dump(exclude_unset=True)
    for field in ("eventAt", "shiftStart", "shiftEnd"):
        if field in updates and updates[field] is not None:
            updates[field] = _to_naive_utc(updates[field])
    instance = await _update_declaration_in_place(db, ShiftCashDeclaration, organization_id, actor_user_id, declaration_id, updates)
    return ShiftCashDeclarationResponse.model_validate(instance)


async def list_shift_cash_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    # STATION_READ comme condition de bascule : c'est exactement ce qui,
    # dans la matrice rôles × vues du prototype, distingue un rôle avec une
    # vue de pilotage station (gérant...) d'un rôle qui n'en a aucune
    # (pompiste, Stations=null) — voir _list_declarations ci-dessus.
    rows, total = await _list_declarations(db, ShiftCashDeclaration, organization_id, actor_user_id, SHIFT_CASH_DECLARATION_READ, pagination, station_id, restrict_to_own_author_unless_permission=STATION_READ)
    return Page(data=[ShiftCashDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_shift_cash_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> ShiftCashDeclarationResponse:
    instance = await _lock_declaration(db, ShiftCashDeclaration, organization_id, actor_user_id, declaration_id)
    return ShiftCashDeclarationResponse.model_validate(instance)


async def create_manual_gauging_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateManualGaugingDeclarationRequest) -> ManualGaugingDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, MANUAL_GAUGING_DECLARATION_CREATE)
    tank = await get_tank(db, organization_id, data.tankId)
    if tank.stationId != station.id:
        raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station indiquée.", status_code=422)
    instance = ManualGaugingDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        tankId=data.tankId,
        declaredHeightMm=data.declaredHeightMm,
        method=data.method,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return ManualGaugingDeclarationResponse.model_validate(instance)


async def update_manual_gauging_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateManualGaugingDeclarationRequest) -> ManualGaugingDeclarationResponse:
    updates = data.model_dump(exclude_unset=True)
    if "eventAt" in updates and updates["eventAt"] is not None:
        updates["eventAt"] = _to_naive_utc(updates["eventAt"])
    instance = await _update_declaration_in_place(db, ManualGaugingDeclaration, organization_id, actor_user_id, declaration_id, updates)
    return ManualGaugingDeclarationResponse.model_validate(instance)


async def list_manual_gauging_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, ManualGaugingDeclaration, organization_id, actor_user_id, MANUAL_GAUGING_DECLARATION_READ, pagination, station_id)
    return Page(data=[ManualGaugingDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_manual_gauging_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> ManualGaugingDeclarationResponse:
    instance = await _lock_declaration(db, ManualGaugingDeclaration, organization_id, actor_user_id, declaration_id)
    return ManualGaugingDeclarationResponse.model_validate(instance)


async def create_quality_check_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateQualityCheckDeclarationRequest) -> QualityCheckDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, QUALITY_CHECK_DECLARATION_CREATE)
    tank = await get_tank(db, organization_id, data.tankId)
    if tank.stationId != station.id:
        raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station indiquée.", status_code=422)
    instance = QualityCheckDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        tankId=data.tankId,
        waterDetected=data.waterDetected,
        waterHeightMm=data.waterHeightMm,
        method=data.method,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return QualityCheckDeclarationResponse.model_validate(instance)


async def update_quality_check_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateQualityCheckDeclarationRequest) -> QualityCheckDeclarationResponse:
    updates = data.model_dump(exclude_unset=True)
    if "eventAt" in updates and updates["eventAt"] is not None:
        updates["eventAt"] = _to_naive_utc(updates["eventAt"])
    instance = await _update_declaration_in_place(db, QualityCheckDeclaration, organization_id, actor_user_id, declaration_id, updates)
    return QualityCheckDeclarationResponse.model_validate(instance)


async def list_quality_check_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, QualityCheckDeclaration, organization_id, actor_user_id, QUALITY_CHECK_DECLARATION_READ, pagination, station_id)
    return Page(data=[QualityCheckDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_quality_check_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> QualityCheckDeclarationResponse:
    instance = await _lock_declaration(db, QualityCheckDeclaration, organization_id, actor_user_id, declaration_id)
    return QualityCheckDeclarationResponse.model_validate(instance)


async def create_leak_test_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateLeakTestDeclarationRequest) -> LeakTestDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, LEAK_TEST_DECLARATION_CREATE)
    tank = await get_tank(db, organization_id, data.tankId)
    if tank.stationId != station.id:
        raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station indiquée.", status_code=422)
    instance = LeakTestDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        tankId=data.tankId,
        result=data.result,
        notes=data.notes,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return LeakTestDeclarationResponse.model_validate(instance)


async def update_leak_test_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateLeakTestDeclarationRequest) -> LeakTestDeclarationResponse:
    updates = data.model_dump(exclude_unset=True)
    if "eventAt" in updates and updates["eventAt"] is not None:
        updates["eventAt"] = _to_naive_utc(updates["eventAt"])
    instance = await _update_declaration_in_place(db, LeakTestDeclaration, organization_id, actor_user_id, declaration_id, updates)
    return LeakTestDeclarationResponse.model_validate(instance)


async def list_leak_test_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, LeakTestDeclaration, organization_id, actor_user_id, LEAK_TEST_DECLARATION_READ, pagination, station_id)
    return Page(data=[LeakTestDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_leak_test_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> LeakTestDeclarationResponse:
    instance = await _lock_declaration(db, LeakTestDeclaration, organization_id, actor_user_id, declaration_id)
    return LeakTestDeclarationResponse.model_validate(instance)


async def create_incident_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateIncidentDeclarationRequest) -> IncidentDeclarationResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, INCIDENT_DECLARATION_CREATE)
    if data.tankId is not None:
        tank = await get_tank(db, organization_id, data.tankId)
        if tank.stationId != station.id:
            raise AppError(code="tank_station_mismatch", message="Cette cuve n'appartient pas à la station indiquée.", status_code=422)
    instance = IncidentDeclaration(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        declaredAt=datetime.now(timezone.utc).replace(tzinfo=None),
        tankId=data.tankId,
        category=data.category,
        description=data.description,
        changeReason=data.changeReason,
        correctsDeclarationId=data.correctsDeclarationId,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return IncidentDeclarationResponse.model_validate(instance)


async def update_incident_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID, data: UpdateIncidentDeclarationRequest) -> IncidentDeclarationResponse:
    updates = data.model_dump(exclude_unset=True)
    if "eventAt" in updates and updates["eventAt"] is not None:
        updates["eventAt"] = _to_naive_utc(updates["eventAt"])
    instance = await _update_declaration_in_place(db, IncidentDeclaration, organization_id, actor_user_id, declaration_id, updates)
    return IncidentDeclarationResponse.model_validate(instance)


async def list_incident_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, IncidentDeclaration, organization_id, actor_user_id, INCIDENT_DECLARATION_READ, pagination, station_id)
    return Page(data=[IncidentDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def lock_incident_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> IncidentDeclarationResponse:
    instance = await _lock_declaration(db, IncidentDeclaration, organization_id, actor_user_id, declaration_id)
    return IncidentDeclarationResponse.model_validate(instance)


# ================================================================
# Couche Approvisionnement (fusion prototype #/livraisons avec la couche
# réelle — décision commanditaire « créer toutes les tables nécessaires,
# même fournisseur », actée avant la fusion de la page). Fournisseur /
# transporteur / camion : référentiels réseau, portée organisation entière
# (la gestion — *_MANAGE — n'est accordée à aucun rôle par défaut : aucune
# vue réseau de gestion n'existe encore ; la lecture est ouverte aux rôles
# qui lisent déjà les livraisons, cf. roles_seed `_APPRO_READ_PERMISSIONS`).
# Commande d'approvisionnement : portée station comme une déclaration
# (jamais de colonne organizationId), cycle de vie piloté par les
# réceptions : 'open' → 'received' au verrouillage de la dernière
# déclaration rattachée qui complète le volume commandé (réceptions
# partielles possibles), jamais d'édition en place.
# ================================================================


async def _get_supplier_or_404(db: AsyncSession, organization_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
    supplier = await db.get(Supplier, supplier_id)
    if supplier is None or supplier.organizationId != organization_id:
        raise AppError(code="supplier_not_found", message="Fournisseur introuvable.", status_code=404)
    return supplier


async def _get_carrier_or_404(db: AsyncSession, organization_id: uuid.UUID, carrier_id: uuid.UUID) -> Carrier:
    carrier = await db.get(Carrier, carrier_id)
    if carrier is None or carrier.organizationId != organization_id:
        raise AppError(code="carrier_not_found", message="Transporteur introuvable.", status_code=404)
    return carrier


async def _get_purchase_order_or_404(db: AsyncSession, organization_id: uuid.UUID, purchase_order_id: uuid.UUID) -> PurchaseOrder:
    """Commande dans la portée de l'organisation — la portée passe par la
    station (même mécanisme que DeclarationMixin), jamais une colonne
    organizationId."""
    purchase_order = await db.get(PurchaseOrder, purchase_order_id)
    if purchase_order is not None:
        station = await db.get(Station, purchase_order.stationId)
        if station is not None and station.organizationId == organization_id:
            return purchase_order
    raise AppError(code="purchase_order_not_found", message="Commande d'approvisionnement introuvable.", status_code=404)


async def create_supplier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateSupplierRequest) -> SupplierResponse:
    await _check_org_scope(db, organization_id, actor_user_id, SUPPLIER_MANAGE)
    instance = Supplier(organizationId=organization_id, **data.model_dump())
    db.add(instance)
    await db.flush()
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.supplier.create", entity_type="Supplier", entity_id=instance.id,
        summary=f"Création du fournisseur {instance.name}",
    )
    await db.commit()
    await db.refresh(instance)
    return SupplierResponse.model_validate(instance)


async def update_supplier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, supplier_id: uuid.UUID, data: UpdateSupplierRequest) -> SupplierResponse:
    await _check_org_scope(db, organization_id, actor_user_id, SUPPLIER_MANAGE)
    supplier = await _get_supplier_or_404(db, organization_id, supplier_id)
    updates = data.model_dump(exclude_unset=True)
    before = {field: getattr(supplier, field) for field in updates}
    for field, value in updates.items():
        if value is not None:
            setattr(supplier, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.supplier.update", entity_type="Supplier", entity_id=supplier.id,
        summary=f"Modification du fournisseur {supplier.name}",
        changes={field: {"before": str(before[field]), "after": str(updates[field])} for field in updates},
    )
    await db.commit()
    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


async def list_suppliers(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, SUPPLIER_READ)
    stmt = select(Supplier).where(Supplier.organizationId == organization_id).order_by(Supplier.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[SupplierResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def create_carrier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateCarrierRequest) -> CarrierResponse:
    await _check_org_scope(db, organization_id, actor_user_id, CARRIER_MANAGE)
    instance = Carrier(organizationId=organization_id, name=data.name)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return CarrierResponse.model_validate(instance)


async def update_carrier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, carrier_id: uuid.UUID, data: UpdateCarrierRequest) -> CarrierResponse:
    await _check_org_scope(db, organization_id, actor_user_id, CARRIER_MANAGE)
    carrier = await _get_carrier_or_404(db, organization_id, carrier_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(carrier, field, value)
    await db.commit()
    await db.refresh(carrier)
    return CarrierResponse.model_validate(carrier)


async def list_carriers(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, CARRIER_READ)
    stmt = select(Carrier).where(Carrier.organizationId == organization_id).order_by(Carrier.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[CarrierResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _ensure_truck_plate_available(db: AsyncSession, organization_id: uuid.UUID, plate_number: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(Truck.id).where(Truck.organizationId == organization_id, Truck.plateNumber == plate_number)
    if exclude_id is not None:
        stmt = stmt.where(Truck.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise AppError(
            code="truck_plate_already_used",
            message=f"Un camion avec l'immatriculation '{plate_number}' existe déjà pour cette organisation.",
            status_code=409,
        )


async def create_truck(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateTruckRequest) -> TruckResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_MANAGE)
    if data.carrierId is not None:
        await _get_carrier_or_404(db, organization_id, data.carrierId)
    await _ensure_truck_plate_available(db, organization_id, data.plateNumber)
    instance = Truck(
        organizationId=organization_id, carrierId=data.carrierId, plateNumber=data.plateNumber,
        capacityLiters=data.capacityLiters, compartmentsCount=data.compartmentsCount,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return TruckResponse.model_validate(instance)


async def update_truck(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, truck_id: uuid.UUID, data: UpdateTruckRequest) -> TruckResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_MANAGE)
    truck = await db.get(Truck, truck_id)
    if truck is None or truck.organizationId != organization_id:
        raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    updates = data.model_dump(exclude_unset=True)
    # Le transporteur n'est vérifié que lorsqu'il change (null explicite =
    # décrocher le camion de son transporteur, autorisé sans vérification).
    if updates.get("carrierId") is not None:
        await _get_carrier_or_404(db, organization_id, updates["carrierId"])
    if updates.get("plateNumber") is not None and updates["plateNumber"] != truck.plateNumber:
        await _ensure_truck_plate_available(db, organization_id, updates["plateNumber"], exclude_id=truck.id)
    for field, value in updates.items():
        setattr(truck, field, value)
    await db.commit()
    await db.refresh(truck)
    return TruckResponse.model_validate(truck)


async def list_trucks(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, carrier_id: uuid.UUID | None = None) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_READ)
    stmt = select(Truck).where(Truck.organizationId == organization_id)
    if carrier_id is not None:
        stmt = stmt.where(Truck.carrierId == carrier_id)
    stmt = stmt.order_by(Truck.plateNumber)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[TruckResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


# Tracking GPS des camions-citernes — service déplacé vers
# `app/location/service.py` (2026-09-15, Phase 2). Fonctions :
# create_gps_device, update_gps_device, unassign_gps_device,
# list_gps_devices, get_or_create_gps_ingest_credential,
# regenerate_gps_ingest_credential, run_truck_stop_detection,
# ingest_truck_position, list_truck_current_positions,
# list_truck_positions, list_truck_stops, get_traccar_connection,
# set_traccar_connection, list_traccar_devices, create_tracking_location,
# update_tracking_location, delete_tracking_location,
# list_tracking_locations, get_tracking_settings,
# update_tracking_settings, create_truck_stop_comment,
# update_truck_stop_comment, delete_truck_stop_comment,
# list_truck_stop_comments, list_truck_stop_reconciliations,
# resolve_truck_stop_reconciliation.



async def assign_truck_to_purchase_order(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID, data: TruckOrderAssignmentRequest) -> TruckOrderAssignmentResponse:
    purchase_order = await _get_purchase_order_or_404(db, organization_id, purchase_order_id)
    station = await db.get(Station, purchase_order.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, TRUCK_ORDER_ASSIGNMENT_MANAGE)
    truck = await db.get(Truck, data.truckId)
    if truck is None or truck.organizationId != organization_id:
        raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    existing_result = await db.execute(
        select(TruckOrderAssignment).where(TruckOrderAssignment.truckId == data.truckId, TruckOrderAssignment.purchaseOrderId == purchase_order_id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        existing.active = True
        await db.commit()
        await db.refresh(existing)
        return TruckOrderAssignmentResponse.model_validate(existing)
    instance = TruckOrderAssignment(truckId=data.truckId, purchaseOrderId=purchase_order_id, active=True)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return TruckOrderAssignmentResponse.model_validate(instance)


async def unassign_truck_from_purchase_order(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID, truck_id: uuid.UUID) -> None:
    purchase_order = await _get_purchase_order_or_404(db, organization_id, purchase_order_id)
    station = await db.get(Station, purchase_order.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, TRUCK_ORDER_ASSIGNMENT_MANAGE)
    result = await db.execute(
        select(TruckOrderAssignment).where(TruckOrderAssignment.truckId == truck_id, TruckOrderAssignment.purchaseOrderId == purchase_order_id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.active = False
        await db.commit()


async def list_trucks_for_purchase_order(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID) -> list[TruckOrderAssignmentResponse]:
    purchase_order = await _get_purchase_order_or_404(db, organization_id, purchase_order_id)
    station = await db.get(Station, purchase_order.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PURCHASE_ORDER_READ)
    result = await db.execute(
        select(TruckOrderAssignment).where(TruckOrderAssignment.purchaseOrderId == purchase_order_id, TruckOrderAssignment.active == True)  # noqa: E712
    )
    return [TruckOrderAssignmentResponse.model_validate(r) for r in result.scalars().all()]


async def list_orders_for_truck(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, truck_id: uuid.UUID) -> list[TruckOrderAssignmentResponse]:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_READ)
    truck = await db.get(Truck, truck_id)
    if truck is None or truck.organizationId != organization_id:
        raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    result = await db.execute(
        select(TruckOrderAssignment).where(TruckOrderAssignment.truckId == truck_id, TruckOrderAssignment.active == True)  # noqa: E712
    )
    return [TruckOrderAssignmentResponse.model_validate(r) for r in result.scalars().all()]


async def _load_purchase_order_lines(db: AsyncSession, purchase_order_id: uuid.UUID) -> list[PurchaseOrderLine]:
    result = await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchaseOrderId == purchase_order_id).order_by(PurchaseOrderLine.createdAt.asc()))
    return list(result.scalars().all())


async def _to_purchase_order_response(db: AsyncSession, purchase_order: PurchaseOrder) -> PurchaseOrderResponse:
    lines = await _load_purchase_order_lines(db, purchase_order.id)
    response = PurchaseOrderResponse.model_validate(purchase_order)
    response.lines = [PurchaseOrderLineResponse.model_validate(l) for l in lines]
    return response


async def create_purchase_order(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreatePurchaseOrderRequest) -> PurchaseOrderResponse:
    """Commande multi-produits (refonte 2026-09-17) — plus de cuve à ce
    niveau (choisie à la livraison, voir `create_delivery_declaration`) :
    une ligne par produit commandé, chacune avec son propre volume."""
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PURCHASE_ORDER_MANAGE)
    supplier = await _get_supplier_or_404(db, organization_id, data.supplierId)
    if not supplier.active:
        raise AppError(code="supplier_inactive", message="Ce fournisseur est inactif — réactivez-le avant de lui passer commande.", status_code=422)
    for line in data.lines:
        await get_fuel_product(db, organization_id, line.fuelProductId)

    instance = PurchaseOrder(
        stationId=station.id,
        supplierId=supplier.id,
        authorUserId=actor_user_id,
        orderReference=data.orderReference,
        orderedAt=datetime.now(timezone.utc).replace(tzinfo=None),
        expectedAt=_to_naive_utc(data.expectedAt),
    )
    db.add(instance)
    await db.flush()
    for line in data.lines:
        db.add(PurchaseOrderLine(purchaseOrderId=instance.id, fuelProductId=line.fuelProductId, orderedVolumeLiters=line.orderedVolumeLiters))
    await db.commit()
    await db.refresh(instance)
    return await _to_purchase_order_response(db, instance)


async def get_purchase_order(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID) -> PurchaseOrderResponse:
    purchase_order = await _get_purchase_order_or_404(db, organization_id, purchase_order_id)
    station = await db.get(Station, purchase_order.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PURCHASE_ORDER_READ)
    return await _to_purchase_order_response(db, purchase_order)


async def generate_purchase_order_document(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID, data: GeneratePurchaseOrderDocumentRequest,
) -> DocumentResponse:
    """Génère un bon de commande PDF ou DOCX (mission « bon de commande +
    aperçu/partage ») et le rattache à la commande via le mécanisme
    Document/DocumentLink générique — même droit que la création de la
    commande elle-même (PURCHASE_ORDER_MANAGE), aucune vérification
    supplémentaire de DOCUMENT_CREATE puisqu'il s'agit d'un document dérivé
    d'une action déjà autorisée, pas d'un upload libre. Chaque génération
    crée un nouveau `Document` (pas de logique de version/supersession dans
    ce lot — choix simple validé avec le commanditaire)."""
    purchase_order = await _get_purchase_order_or_404(db, organization_id, purchase_order_id)
    station = await db.get(Station, purchase_order.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PURCHASE_ORDER_MANAGE)
    order_lines = await _load_purchase_order_lines(db, purchase_order.id)
    lines = [(line, await get_fuel_product(db, organization_id, line.fuelProductId)) for line in order_lines]
    supplier = await _get_supplier_or_404(db, organization_id, purchase_order.supplierId)

    if data.format == "pdf":
        file_bytes = generate_purchase_order_pdf(purchase_order, lines, supplier, station)
        file_name = f"bon-commande-{purchase_order.orderReference}.pdf"
        mime_type = "application/pdf"
    else:
        file_bytes = generate_purchase_order_docx(purchase_order, lines, supplier, station)
        file_name = f"bon-commande-{purchase_order.orderReference}.docx"
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    storage_reference = get_storage_backend().upload(file_bytes, file_name, organization_id)
    document = await files_service.create_document_for_trusted_caller(
        db, organization_id, actor_user_id,
        storage_reference=storage_reference, file_name=file_name, mime_type=mime_type,
        linked_entity_type="PurchaseOrder", linked_entity_id=purchase_order.id,
    )
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.purchaseOrder.generateDocument", entity_type="PurchaseOrder", entity_id=purchase_order.id,
        summary=f"Génération du bon de commande {purchase_order.orderReference} ({data.format})",
    )
    await db.commit()
    return document


async def list_purchase_orders(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None = None) -> Page:
    """Même mécanisme de portée que `_list_declarations` (stations visibles
    de l'acteur via PURCHASE_ORDER_READ) — une commande est scopée station,
    un rôle scopé station ne voit que les commandes de ses stations."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, PURCHASE_ORDER_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PURCHASE_ORDER_READ}.", status_code=403)
    if station_id is not None and not sees_all and station_id not in visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {PURCHASE_ORDER_READ}.", status_code=403)

    stmt = select(PurchaseOrder).join(Station, Station.id == PurchaseOrder.stationId).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(PurchaseOrder.stationId.in_(visible_station_ids))
    if station_id is not None:
        stmt = stmt.where(PurchaseOrder.stationId == station_id)
    stmt = stmt.order_by(PurchaseOrder.orderedAt.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    data = [await _to_purchase_order_response(db, r) for r in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _receive_purchase_order_line_if_complete(db: AsyncSession, purchase_order_line_id: uuid.UUID) -> None:
    """Recalcule le statut d'UNE ligne de commande (un produit), puis
    ré-agrège le statut de la commande entière depuis toutes ses lignes
    (refonte 2026-09-17 — remplace `_receive_purchase_order_if_complete`,
    qui raisonnait sur la commande entière avant la refonte multi-produits).
    Évalué à chaque verrouillage d'une ligne de déclaration de livraison
    rattachée (jamais à la création : une déclaration 'declared' reste
    révisable — voir `lock_delivery_declaration`). Le cumul ne compte que
    les lignes de déclaration ACTIVES : non supplantées par une correction
    ciblée (`DeliveryDeclarationLine.correctsLineId`) et dont la déclaration
    parente n'est pas elle-même supplantée (`correctsDeclarationId`)."""
    line = await db.get(PurchaseOrderLine, purchase_order_line_id)
    if line is None:
        return
    superseded_line_ids = select(DeliveryDeclarationLine.correctsLineId).where(DeliveryDeclarationLine.correctsLineId.is_not(None))
    superseded_declaration_ids = select(DeliveryDeclaration.correctsDeclarationId).where(DeliveryDeclaration.correctsDeclarationId.is_not(None))
    received_total = await db.scalar(
        select(func.coalesce(func.sum(DeliveryDeclarationLine.volumeLiters), 0))
        .join(DeliveryDeclaration, DeliveryDeclaration.id == DeliveryDeclarationLine.declarationId)
        .where(
            DeliveryDeclarationLine.purchaseOrderLineId == purchase_order_line_id,
            DeliveryDeclaration.lifecycleStatus.in_(("declared", "locked")),
            DeliveryDeclarationLine.id.not_in(superseded_line_ids),
            DeliveryDeclaration.id.not_in(superseded_declaration_ids),
        )
    )
    received_total = float(received_total or 0)
    if received_total <= 0:
        line.status = "open"
    elif received_total >= float(line.orderedVolumeLiters):
        line.status = "received"
    else:
        line.status = "partially_received"
    await db.flush()

    order = await db.get(PurchaseOrder, line.purchaseOrderId)
    all_lines = await _load_purchase_order_lines(db, order.id)
    statuses = {l.status for l in all_lines}
    if statuses == {"received"}:
        order.status = "received"
    elif statuses == {"open"}:
        order.status = "open"
    else:
        order.status = "partially_received"
    await db.commit()


# ================================================================
# Couche Commercial (processus-double-sources-verite, Phase 5 §5, Phase 7
# §2-4) — Bloc 3/4. Portée organisation entière pour tout sauf Sale (scopée
# station, même mécanisme que la couche déclarative).
# ================================================================


async def _check_org_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)


async def _get_commercial_account_or_404(db: AsyncSession, organization_id: uuid.UUID, account_id: uuid.UUID) -> CommercialAccount:
    account = await db.get(CommercialAccount, account_id)
    if account is None or account.organizationId != organization_id:
        raise AppError(code="commercial_account_not_found", message="Compte client introuvable.", status_code=404)
    return account


async def create_commercial_account(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateCommercialAccountRequest) -> CommercialAccountResponse:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_MANAGE)
    currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
    if currency_result.scalar_one_or_none() is None:
        raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
    instance = CommercialAccount(organizationId=organization_id, name=data.name, currencyId=data.currencyId, creditLimit=data.creditLimit)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return CommercialAccountResponse.model_validate(instance)


async def update_commercial_account(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, account_id: uuid.UUID, data: UpdateCommercialAccountRequest) -> CommercialAccountResponse:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_MANAGE)
    account = await _get_commercial_account_or_404(db, organization_id, account_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(account, field, value)
    await db.commit()
    await db.refresh(account)
    return CommercialAccountResponse.model_validate(account)


async def list_commercial_accounts(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_READ)
    stmt = select(CommercialAccount).where(CommercialAccount.organizationId == organization_id).order_by(CommercialAccount.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[CommercialAccountResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def create_vehicle(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateVehicleRequest) -> VehicleResponse:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_MANAGE)
    await _get_commercial_account_or_404(db, organization_id, data.commercialAccountId)
    instance = Vehicle(commercialAccountId=data.commercialAccountId, plateOrReference=data.plateOrReference)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return VehicleResponse.model_validate(instance)


async def create_driver(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateDriverRequest) -> DriverResponse:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_MANAGE)
    if data.commercialAccountId is not None:
        await _get_commercial_account_or_404(db, organization_id, data.commercialAccountId)
    instance = Driver(commercialAccountId=data.commercialAccountId, name=data.name)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return DriverResponse.model_validate(instance)


async def create_authorization(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateAuthorizationRequest) -> AuthorizationResponse:
    await _check_org_scope(db, organization_id, actor_user_id, COMMERCIAL_ACCOUNT_MANAGE)
    account = await _get_commercial_account_or_404(db, organization_id, data.commercialAccountId)
    if data.vehicleId is not None:
        vehicle = await db.get(Vehicle, data.vehicleId)
        if vehicle is None or vehicle.commercialAccountId != account.id:
            raise AppError(code="vehicle_not_found", message="Véhicule introuvable pour ce compte.", status_code=404)
    if data.driverId is not None:
        driver = await db.get(Driver, data.driverId)
        if driver is None:
            raise AppError(code="driver_not_found", message="Conducteur introuvable.", status_code=404)
    instance = Authorization(commercialAccountId=account.id, vehicleId=data.vehicleId, driverId=data.driverId, reference=data.reference)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return AuthorizationResponse.model_validate(instance)


async def create_sale(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateSaleRequest) -> SaleResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, SALE_CREATE)
    await get_fuel_product(db, organization_id, data.fuelProductId)
    currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
    if currency_result.scalar_one_or_none() is None:
        raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)

    account: CommercialAccount | None = None
    if data.paymentMethod == "credit":
        if data.commercialAccountId is None:
            raise AppError(code="commercial_account_required", message="commercialAccountId est obligatoire pour une vente à crédit.", status_code=422)
        account = await _get_commercial_account_or_404(db, organization_id, data.commercialAccountId)
        if not account.active:
            raise AppError(code="commercial_account_inactive", message="Ce compte client est inactif.", status_code=422)
        sale_amount = data.quantityLiters * data.priceAmount
        # Vérification de cohérence (Phase 6 §5.1 de 06-mecanisme-rapprochement.md,
        # blocage à la saisie décidé en Phase 7 addendum point 2) : la somme des
        # créances encore ouvertes plus cette vente ne doit jamais dépasser la
        # limite du compte — bloquant, sans exception de rôle.
        outstanding_result = await db.execute(
            select(func.coalesce(func.sum(Receivable.amount), 0)).where(
                Receivable.commercialAccountId == account.id, Receivable.status.in_(("open", "partially_settled"))
            )
        )
        outstanding = float(outstanding_result.scalar_one())
        if outstanding + sale_amount > float(account.creditLimit):
            raise AppError(
                code="credit_limit_exceeded",
                message=f"Cette vente dépasserait la limite de crédit du compte ({account.creditLimit}).",
                status_code=422,
            )
    elif data.commercialAccountId is not None:
        raise AppError(code="commercial_account_not_applicable", message="commercialAccountId ne s'applique qu'à une vente à crédit.", status_code=422)

    if data.vehicleId is not None and await db.get(Vehicle, data.vehicleId) is None:
        raise AppError(code="vehicle_not_found", message="Véhicule introuvable.", status_code=404)
    if data.driverId is not None and await db.get(Driver, data.driverId) is None:
        raise AppError(code="driver_not_found", message="Conducteur introuvable.", status_code=404)
    if data.pumpId is not None:
        pump = await db.get(Pump, data.pumpId)
        if pump is None or pump.stationId != station.id:
            raise AppError(code="pump_not_found", message="Pompe introuvable pour cette station.", status_code=404)

    sale = Sale(
        stationId=station.id,
        authorUserId=actor_user_id,
        eventAt=_to_naive_utc(data.eventAt),
        fuelProductId=data.fuelProductId,
        quantityLiters=data.quantityLiters,
        priceAmount=data.priceAmount,
        currencyId=data.currencyId,
        paymentMethod=data.paymentMethod,
        commercialAccountId=data.commercialAccountId,
        vehicleId=data.vehicleId,
        driverId=data.driverId,
        pumpId=data.pumpId,
    )
    db.add(sale)
    await db.flush()

    if data.paymentMethod == "credit":
        db.add(Receivable(commercialAccountId=account.id, saleId=sale.id, amount=data.quantityLiters * data.priceAmount, currencyId=data.currencyId, status="open"))

    await db.commit()
    await db.refresh(sale)

    # Mission détection de pertes phase 2 (2026-09-18) : la déclaration
    # elle-même réveille la vérification déclaré/détecté, jamais une tâche
    # planifiée (aucune n'existe dans cette application). Ne bloque jamais
    # la déclaration de vente : une panne de ce côté ne doit jamais empêcher
    # un gérant de déclarer sa vente.
    if data.pumpId is not None:
        try:
            tank = await get_tank(db, organization_id, pump.tankId)
            await _trigger_stock_discrepancy_alert(db, tank, sale.eventAt.date())
        except Exception:
            logger.exception("Échec du déclenchement de l'alerte stock_declared_discrepancy après create_sale (sale=%s)", sale.id)

    return SaleResponse.model_validate(sale)


async def bulk_import_sales(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: BulkImportSalesRequest
) -> BulkImportSalesResponse:
    """Dernière ligne de défense d'un import de ventes (même philosophie que
    bulk_import_sellable_products) — chaque ligne est vérifiée et insérée
    indépendamment (savepoint) pour qu'une ligne invalide n'annule jamais les
    lignes valides du même fichier, tout en rapportant une erreur précise
    par ligne (jamais un rejet global opaque). Reprend telles quelles les
    règles métier de create_sale (portée de déclaration, pompe de la
    station, limite de crédit)."""
    created_count = 0
    errors: list[BulkImportRowError] = []
    station_cache: dict[uuid.UUID, Station | None] = {}
    currency_ids = {row.currencyId for row in data.rows}
    known_currencies = set(
        (await db.execute(select(Currency.id).where(Currency.id.in_(currency_ids)))).scalars().all()
    )
    # Mission détection de pertes phase 2 (2026-09-18) : une (cuve, jour)
    # par ligne créée avec succès, dédupliquée — un import de plusieurs
    # lignes sur la même cuve/jour ne déclenche qu'une seule vérification,
    # après le commit final, jamais une par ligne.
    tanks_days_to_check: dict[tuple[uuid.UUID, date], Tank] = {}

    for row in data.rows:
        if row.indexEnd <= row.indexStart:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="L'index de fin doit être supérieur à l'index de début."))
            continue

        if row.stationId not in station_cache:
            candidate = await db.get(Station, row.stationId)
            station_cache[row.stationId] = candidate if candidate is not None and candidate.organizationId == organization_id else None
        station = station_cache[row.stationId]
        if station is None:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Station introuvable dans cette organisation."))
            continue

        try:
            await _check_declaration_scope(db, organization_id, actor_user_id, station, SALE_CREATE)
        except AppError:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Permission manquante pour déclarer une vente sur cette station."))
            continue

        pump = await db.get(Pump, row.pumpId)
        if pump is None:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Pompe introuvable."))
            continue
        if pump.stationId != station.id:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Cette pompe n'appartient pas à la station indiquée."))
            continue

        tank = await db.get(Tank, pump.tankId)
        if tank is None:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Cuve associée à la pompe introuvable."))
            continue
        fuel_product_id = tank.fuelProductId

        if row.currencyId not in known_currencies:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Devise introuvable."))
            continue

        account: CommercialAccount | None = None
        quantity_liters = row.indexEnd - row.indexStart
        if row.paymentMethod == "credit":
            if row.commercialAccountId is None:
                errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="commercialAccountId est obligatoire pour une vente à crédit."))
                continue
            try:
                account = await _get_commercial_account_or_404(db, organization_id, row.commercialAccountId)
            except AppError:
                errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Compte client introuvable."))
                continue
            if not account.active:
                errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Ce compte client est inactif."))
                continue
            sale_amount = quantity_liters * row.priceAmount
            outstanding_result = await db.execute(
                select(func.coalesce(func.sum(Receivable.amount), 0)).where(
                    Receivable.commercialAccountId == account.id, Receivable.status.in_(("open", "partially_settled"))
                )
            )
            outstanding = float(outstanding_result.scalar_one())
            if outstanding + sale_amount > float(account.creditLimit):
                errors.append(
                    BulkImportRowError(
                        rowNumber=row.rowNumber,
                        message=f"Cette vente dépasserait la limite de crédit du compte ({account.creditLimit}).",
                    )
                )
                continue

        try:
            async with db.begin_nested():
                sale = Sale(
                    stationId=station.id,
                    authorUserId=actor_user_id,
                    eventAt=_to_naive_utc(row.eventAt),
                    fuelProductId=fuel_product_id,
                    quantityLiters=quantity_liters,
                    priceAmount=row.priceAmount,
                    currencyId=row.currencyId,
                    paymentMethod=row.paymentMethod,
                    commercialAccountId=row.commercialAccountId,
                    pumpId=row.pumpId,
                )
                db.add(sale)
                await db.flush()

                if row.paymentMethod == "credit":
                    db.add(Receivable(commercialAccountId=account.id, saleId=sale.id, amount=quantity_liters * row.priceAmount, currencyId=row.currencyId, status="open"))
        except IntegrityError:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Impossible d'enregistrer cette vente."))
            continue
        created_count += 1
        tanks_days_to_check[(tank.id, _to_naive_utc(row.eventAt).date())] = tank

    await db.commit()

    # Mission détection de pertes phase 2 : ne bloque jamais l'import lui-même.
    for (_, day), tank in tanks_days_to_check.items():
        try:
            await _trigger_stock_discrepancy_alert(db, tank, day)
        except Exception:
            logger.exception("Échec du déclenchement de l'alerte stock_declared_discrepancy après bulk_import_sales (tank=%s, day=%s)", tank.id, day)

    return BulkImportSalesResponse(createdCount=created_count, errors=errors)


async def list_sales(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_declarations(db, Sale, organization_id, actor_user_id, SALE_READ, pagination, station_id)
    return Page(data=[SaleResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def list_receivables(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, commercial_account_id: uuid.UUID | None) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, RECEIVABLE_READ)
    stmt = select(Receivable).join(CommercialAccount, CommercialAccount.id == Receivable.commercialAccountId).where(CommercialAccount.organizationId == organization_id)
    if commercial_account_id is not None:
        stmt = stmt.where(Receivable.commercialAccountId == commercial_account_id)
    stmt = stmt.order_by(Receivable.createdAt.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[ReceivableResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def create_payment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreatePaymentRequest) -> PaymentResponse:
    await _check_org_scope(db, organization_id, actor_user_id, PAYMENT_CREATE)
    receivable = await db.get(Receivable, data.receivableId)
    if receivable is None:
        raise AppError(code="receivable_not_found", message="Créance introuvable.", status_code=404)
    await _get_commercial_account_or_404(db, organization_id, receivable.commercialAccountId)
    if receivable.status == "settled":
        raise AppError(code="receivable_already_settled", message="Cette créance est déjà soldée.", status_code=409)

    currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
    if currency_result.scalar_one_or_none() is None:
        raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)

    if data.currencyId != receivable.currencyId and data.exchangeRateApplied is None:
        raise AppError(
            code="exchange_rate_required",
            message="exchangeRateApplied est obligatoire quand la devise du paiement diffère de celle de la créance (Phase 5 §5.1).",
            status_code=422,
        )

    payment = Payment(
        receivableId=receivable.id,
        authorUserId=actor_user_id,
        paidAt=_to_naive_utc(data.paidAt),
        amount=data.amount,
        currencyId=data.currencyId,
        exchangeRateApplied=data.exchangeRateApplied,
        method=data.method,
    )
    db.add(payment)
    await db.flush()

    # Recalcule le statut de la créance à partir de TOUS ses paiements —
    # conversion uniquement via le taux capturé à chaque paiement (jamais un
    # taux vivant recalculé après coup, Phase 5 §5.1). Convention :
    # exchangeRateApplied = unités de la devise de la créance pour 1 unité
    # de la devise du paiement.
    paid_result = await db.execute(select(Payment).where(Payment.receivableId == receivable.id))
    total_paid_in_receivable_currency = 0.0
    for p in paid_result.scalars().all():
        if p.currencyId == receivable.currencyId:
            total_paid_in_receivable_currency += float(p.amount)
        elif p.exchangeRateApplied:
            total_paid_in_receivable_currency += float(p.amount) * float(p.exchangeRateApplied)
    if total_paid_in_receivable_currency >= float(receivable.amount):
        receivable.status = "settled"
    elif total_paid_in_receivable_currency > 0:
        receivable.status = "partially_settled"

    await db.commit()
    await db.refresh(payment)
    return PaymentResponse.model_validate(payment)


async def list_payments(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, receivable_id: uuid.UUID | None) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, PAYMENT_READ)
    stmt = (
        select(Payment)
        .join(Receivable, Receivable.id == Payment.receivableId)
        .join(CommercialAccount, CommercialAccount.id == Receivable.commercialAccountId)
        .where(CommercialAccount.organizationId == organization_id)
    )
    if receivable_id is not None:
        stmt = stmt.where(Payment.receivableId == receivable_id)
    stmt = stmt.order_by(Payment.paidAt.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[PaymentResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


# ================================================================
# Rapprochement (processus-double-sources-verite, Phase 6, Phase 7 §1) —
# Bloc 6 : configuration des tolérances par station + lecture des résultats.
# Le calcul lui-même (écriture de ReconciliationRecord) est le Bloc 7.
# ================================================================


async def get_station_reconciliation_settings(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> StationReconciliationSettingsResponse | None:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_SETTINGS_MANAGE)
    result = await db.execute(select(StationReconciliationSettings).where(StationReconciliationSettings.stationId == station.id))
    instance = result.scalar_one_or_none()
    return StationReconciliationSettingsResponse.model_validate(instance) if instance is not None else None


async def upsert_station_reconciliation_settings(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, data: UpsertStationReconciliationSettingsRequest) -> StationReconciliationSettingsResponse:
    """Un seul enregistrement par station — remplace la dérogation
    existante plutôt que d'en accumuler (contrairement aux entités
    déclaratives/historiques, une configuration est un état courant, pas un
    historique à conserver)."""
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_SETTINGS_MANAGE)
    result = await db.execute(select(StationReconciliationSettings).where(StationReconciliationSettings.stationId == station.id))
    instance = result.scalar_one_or_none()
    updates = data.model_dump()
    if instance is None:
        instance = StationReconciliationSettings(stationId=station.id, **updates)
        db.add(instance)
    else:
        for field, value in updates.items():
            setattr(instance, field, value)
    await db.commit()
    await db.refresh(instance)
    return StationReconciliationSettingsResponse.model_validate(instance)


async def list_reconciliation_records(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, subject_type: str | None, subject_id: uuid.UUID | None
) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, RECONCILIATION_READ)
    stmt = select(ReconciliationRecord)
    if subject_type is not None:
        stmt = stmt.where(ReconciliationRecord.subjectType == subject_type)
    if subject_id is not None:
        stmt = stmt.where(ReconciliationRecord.subjectId == subject_id)
    stmt = stmt.order_by(ReconciliationRecord.evaluatedAt.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[ReconciliationRecordResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


# ================================================================
# Mécanisme de calcul du rapprochement (processus-double-sources-verite,
# Phase 6 §3-5, Phase 7 addendum §5) — Bloc 7. Calcul paresseux à la
# demande, jamais une tâche planifiée (même pattern que
# `_get_or_compute_tank_cash_for_day` ci-dessus, Phase 6 §0) : chaque
# évaluation crée un nouveau `ReconciliationRecord` (historisé, jamais
# réécrit, Phase 6 §2) et met à jour le pointeur `reconciledWithId`/
# `reconciledWithType` de l'entité source vers ce nouveau résultat.
# ================================================================


async def _get_reconciliation_settings(db: AsyncSession, station_id: uuid.UUID) -> StationReconciliationSettings | None:
    result = await db.execute(select(StationReconciliationSettings).where(StationReconciliationSettings.stationId == station_id))
    return result.scalar_one_or_none()


def _tolerance(settings: StationReconciliationSettings | None, field: str, default: float) -> float:
    if settings is not None:
        value = getattr(settings, field)
        if value is not None:
            return float(value)
    return default


async def _record_reconciliation(
    db: AsyncSession,
    subject_type: str,
    subject_id: uuid.UUID,
    counterpart_type: str | None,
    counterpart_id: str | None,
    family: str,
    status: str,
    discrepancy_value: float | None,
    discrepancy_unit: str | None,
    tolerance_applied: float | None,
    evaluated_by_user_id: uuid.UUID | None = None,
) -> ReconciliationRecord:
    record = ReconciliationRecord(
        subjectType=subject_type,
        subjectId=subject_id,
        counterpartType=counterpart_type,
        counterpartId=counterpart_id,
        family=family,
        status=status,
        discrepancyValue=discrepancy_value,
        discrepancyUnit=discrepancy_unit,
        toleranceApplied=tolerance_applied,
        evaluatedAt=datetime.now(timezone.utc).replace(tzinfo=None),
        # None = calcul automatique — jamais une chaîne magique "system"
        # (Phase 6 §2) ; un rapprochement MANUEL (mission « rapprochement
        # manuel », 2026-09-17) passe l'acteur humain qui a choisi le
        # candidat, pour distinguer clairement les deux dans l'historique.
        evaluatedByUserId=evaluated_by_user_id,
    )
    db.add(record)
    await db.flush()
    return record


async def _find_active_line_using_detected(db: AsyncSession, detected_id: uuid.UUID, exclude_line_id: uuid.UUID | None = None) -> DeliveryDeclarationLine | None:
    """Cherche si une détection sert déjà de contrepartie CONFIRMÉE (matched
    ou discrepancy — jamais "pending"/"insufficient_data", qui ne
    consomment rien) à une ligne de déclaration encore ACTIVE (non
    supplantée par une correction ciblée). Sert à éviter qu'une même montée
    de niveau physique soit silencieusement rapprochée avec deux
    déclarations différentes (scénario 4, validé avec le commanditaire) —
    jamais un blocage dur, juste un signal explicite avant confirmation."""
    superseded_line_ids = select(DeliveryDeclarationLine.correctsLineId).where(DeliveryDeclarationLine.correctsLineId.is_not(None))
    stmt = (
        select(DeliveryDeclarationLine)
        .join(ReconciliationRecord, ReconciliationRecord.id == DeliveryDeclarationLine.reconciledWithId)
        .where(
            ReconciliationRecord.counterpartType == "DeliveryDetected",
            ReconciliationRecord.counterpartId == str(detected_id),
            ReconciliationRecord.status.in_(("matched", "discrepancy")),
            DeliveryDeclarationLine.id.not_in(superseded_line_ids),
        )
    )
    if exclude_line_id is not None:
        stmt = stmt.where(DeliveryDeclarationLine.id != exclude_line_id)
    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def _is_delivery_declaration_line_superseded(db: AsyncSession, line_id: uuid.UUID) -> bool:
    result = await db.execute(select(DeliveryDeclarationLine.id).where(DeliveryDeclarationLine.correctsLineId == line_id).limit(1))
    return result.scalar_one_or_none() is not None


async def _evaluate_delivery_declaration_line_reconciliation_core(db: AsyncSession, declaration: DeliveryDeclaration, line: DeliveryDeclarationLine) -> ReconciliationRecord:
    """Cœur du rapprochement d'UNE ligne de livraison <-> `DeliveryDetected`,
    sans vérification de permission — appelé à la fois par l'endpoint
    manuel (`evaluate_delivery_declaration_reconciliation`, ci-dessous) et
    par les déclenchements automatiques (mission « flux de livraison
    station ») : à la création d'une déclaration, et en retour depuis une
    détection nouvellement créée (`run_delivery_detection_for_tank`).

    Refonte 2026-09-17 : le rapprochement se fait désormais par LIGNE, sur
    la cuve exacte qu'elle désigne (`DeliveryDeclarationLine.tankId`), et
    non plus par station+produit+fenêtre de temps — l'ancien mécanisme
    choisissait arbitrairement la détection la plus proche en temps quand
    plusieurs cuves du même produit recevaient simultanément (scénario B),
    laissant les autres cuves faussement « non rapprochées ». Fenêtre
    temporelle + tolérance de volume `max(fixe, pourcentage du volume
    déclaré)` (Phase 7 addendum §1) — logique de recherche du meilleur
    candidat inchangée, restreinte à cette seule cuve. Crée en plus l'alerte
    `delivery_discrepancy` quand l'écart dépasse la tolérance."""
    settings = await _get_reconciliation_settings(db, declaration.stationId)
    window_hours = _tolerance(settings, "deliveryWindowHours", RECONCILIATION_DELIVERY_WINDOW_HOURS_DEFAULT)
    fixed_tolerance = _tolerance(settings, "deliveryVolumeToleranceFixedLiters", RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_FIXED_LITERS_DEFAULT)
    percent_tolerance = _tolerance(settings, "deliveryVolumeTolerancePercent", RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_PERCENT_DEFAULT)

    window_start = declaration.eventAt - timedelta(hours=window_hours)
    window_end = declaration.eventAt + timedelta(hours=window_hours)
    candidates_result = await db.execute(
        select(DeliveryDetected).where(
            DeliveryDetected.tankId == line.tankId,
            DeliveryDetected.startTime >= window_start,
            DeliveryDetected.startTime <= window_end,
        )
    )
    best, best_delta = None, None
    for candidate in candidates_result.scalars().all():
        # Scénario 4 (validé avec le commanditaire) : une détection déjà
        # confirmée (matched/discrepancy) pour une AUTRE ligne active ne
        # doit plus être proposée automatiquement — une même montée de
        # niveau physique ne correspond jamais à deux livraisons distinctes.
        # Reste disponible en rapprochement MANUEL (voir
        # `list_delivery_declaration_line_reconciliation_candidates`), avec
        # confirmation explicite requise (`force=true`).
        if await _find_active_line_using_detected(db, candidate.id, exclude_line_id=line.id) is not None:
            continue
        delta = abs((candidate.startTime - declaration.eventAt).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = candidate, delta

    counterpart_type: str | None = None
    counterpart_id: str | None = None
    discrepancy_value: float | None = None
    tolerance_applied: float | None = None
    if best is None:
        status = "pending"  # aucune contrepartie détectée dans la fenêtre — jamais interprété comme une anomalie
    else:
        counterpart_type, counterpart_id = "DeliveryDetected", str(best.id)
        if best.volumeLiters is None:
            status = "insufficient_data"
        else:
            tolerance_applied = max(fixed_tolerance, float(line.volumeLiters) * percent_tolerance / 100)
            discrepancy_value = abs(float(line.volumeLiters) - float(best.volumeLiters))
            status = "matched" if discrepancy_value <= tolerance_applied else "discrepancy"

    record = await _record_reconciliation(
        db, "DeliveryDeclarationLine", line.id, counterpart_type, counterpart_id,
        "quantitative", status, discrepancy_value, "liters" if discrepancy_value is not None else None, tolerance_applied,
    )
    line.reconciledWithId = record.id
    line.reconciledWithType = "ReconciliationRecord"

    if status == "discrepancy" and best is not None:
        await _create_alert_if_not_already_active(
            db, line.tankId, "delivery_discrepancy", declaration.eventAt, discrepancy_value, tolerance_applied
        )
    elif status == "matched" and best is not None:
        # D2 : un appariement réussi EST la vérité qui referme les alertes
        # de ce cycle de livraison — jamais un clic humain. `delivery_undeclared`
        # n'a plus lieu d'être (la détection a maintenant une déclaration) ;
        # `delivery_declaration_pending` non plus, sur CETTE cuve précise
        # (refonte 2026-09-17 : plus besoin de balayer toutes les cuves du
        # même produit, la ligne désigne la cuve exacte).
        resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_discrepancy", resolved_at=resolved_at)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_undeclared", resolved_at=resolved_at)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_declaration_pending", resolved_at=resolved_at)

    await db.commit()
    await db.refresh(record)
    return record


async def evaluate_delivery_declaration_reconciliation(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> list[ReconciliationRecordResponse]:
    """Rapprochement opérationnel (Phase 5 §4), déclenchable manuellement
    (« action rapide » du commanditaire — bouton de ré-évaluation sur une
    déclaration/alerte) en plus des déclenchements automatiques. Une
    déclaration peut porter plusieurs lignes (refonte 2026-09-17) — chacune
    se rapproche indépendamment, la liste complète des résultats est
    retournée."""
    declaration = await _get_declaration_or_404(db, DeliveryDeclaration, organization_id, declaration_id)
    station = await db.get(Station, declaration.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_READ)
    lines = await _load_delivery_declaration_lines(db, declaration.id)
    records = [await _evaluate_delivery_declaration_line_reconciliation_core(db, declaration, line) for line in lines]
    return [ReconciliationRecordResponse.model_validate(r) for r in records]


async def _get_delivery_declaration_line_and_context(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID) -> tuple[DeliveryDeclarationLine, DeliveryDeclaration, Station]:
    line = await db.get(DeliveryDeclarationLine, line_id)
    if line is None:
        raise AppError(code="delivery_declaration_line_not_found", message="Ligne de livraison introuvable.", status_code=404)
    declaration = await db.get(DeliveryDeclaration, line.declarationId)
    station = await db.get(Station, declaration.stationId) if declaration is not None else None
    if declaration is None or station is None or station.organizationId != organization_id:
        raise AppError(code="delivery_declaration_line_not_found", message="Ligne de livraison introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_READ)
    return line, declaration, station


async def list_delivery_declaration_line_reconciliation_candidates(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID
) -> list[DeliveryReconciliationCandidateResponse]:
    """Liste des détections candidates pour le rapprochement MANUEL d'une
    ligne (mission « rapprochement manuel », 2026-09-17) — jamais un choix
    silencieux : la personne habilitée voit tous les candidats de la
    fenêtre, avec leur écart en temps et un signal explicite si un autre
    candidat est déjà utilisé ailleurs (scénario 4)."""
    line, declaration, _station = await _get_delivery_declaration_line_and_context(db, organization_id, actor_user_id, line_id)
    settings = await _get_reconciliation_settings(db, declaration.stationId)
    window_hours = _tolerance(settings, "deliveryWindowHours", RECONCILIATION_DELIVERY_WINDOW_HOURS_DEFAULT)
    window_start = declaration.eventAt - timedelta(hours=window_hours)
    window_end = declaration.eventAt + timedelta(hours=window_hours)
    result = await db.execute(
        select(DeliveryDetected)
        .where(DeliveryDetected.tankId == line.tankId, DeliveryDetected.startTime >= window_start, DeliveryDetected.startTime <= window_end)
        .order_by(DeliveryDetected.startTime.asc())
    )
    tank = await db.get(Tank, line.tankId)
    candidates: list[DeliveryReconciliationCandidateResponse] = []
    for detected in result.scalars().all():
        delta_minutes = abs((detected.startTime - declaration.eventAt).total_seconds()) / 60
        used_by = await _find_active_line_using_detected(db, detected.id, exclude_line_id=line.id)
        candidates.append(
            DeliveryReconciliationCandidateResponse(
                detected=_delivery_to_response(detected, tank),
                deltaMinutes=round(delta_minutes, 1),
                alreadyReconciledWith=used_by.id if used_by is not None else None,
            )
        )
    return candidates


async def manually_reconcile_delivery_declaration_line(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, line_id: uuid.UUID, data: ManualReconcileDeliveryDeclarationLineRequest
) -> ReconciliationRecordResponse:
    """Rapprochement MANUEL : la personne habilitée choisit elle-même la
    détection avec laquelle rapprocher cette ligne, plutôt que de subir le
    choix automatique « la plus proche en temps » — utile quand plusieurs
    candidats existent dans la fenêtre (scénario 3) ou que l'automatique
    n'a rien trouvé (fenêtre mal calée, scénario 6 : le choix manuel n'a
    pas la même contrainte de fenêtre stricte que l'automatique, la
    personne peut choisir n'importe quel candidat listé). Une ligne déjà
    remplacée par une correction ciblée ne peut plus être rapprochée — le
    rapprochement doit se faire sur la nouvelle ligne (scénario 5)."""
    line, declaration, _station = await _get_delivery_declaration_line_and_context(db, organization_id, actor_user_id, line_id)
    if await _is_delivery_declaration_line_superseded(db, line.id):
        raise AppError(code="delivery_declaration_line_superseded", message="Cette ligne a été remplacée par une correction — rapprochez la nouvelle ligne.", status_code=409)

    detected = await db.get(DeliveryDetected, data.detectedId)
    if detected is None or detected.tankId != line.tankId:
        raise AppError(code="delivery_detected_not_found", message="Détection introuvable pour cette cuve.", status_code=404)

    used_by = await _find_active_line_using_detected(db, detected.id, exclude_line_id=line.id)
    if used_by is not None and not data.force:
        raise AppError(
            code="delivery_detected_already_reconciled",
            message="Cette détection est déjà rapprochée avec une autre ligne — confirmez explicitement (force) pour la partager quand même.",
            status_code=409,
        )

    settings = await _get_reconciliation_settings(db, declaration.stationId)
    fixed_tolerance = _tolerance(settings, "deliveryVolumeToleranceFixedLiters", RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_FIXED_LITERS_DEFAULT)
    percent_tolerance = _tolerance(settings, "deliveryVolumeTolerancePercent", RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_PERCENT_DEFAULT)

    if detected.volumeLiters is None:
        status, discrepancy_value, tolerance_applied = "insufficient_data", None, None
    else:
        tolerance_applied = max(fixed_tolerance, float(line.volumeLiters) * percent_tolerance / 100)
        discrepancy_value = abs(float(line.volumeLiters) - float(detected.volumeLiters))
        status = "matched" if discrepancy_value <= tolerance_applied else "discrepancy"

    record = await _record_reconciliation(
        db, "DeliveryDeclarationLine", line.id, "DeliveryDetected", str(detected.id),
        "quantitative", status, discrepancy_value, "liters" if discrepancy_value is not None else None, tolerance_applied,
        evaluated_by_user_id=actor_user_id,
    )
    line.reconciledWithId = record.id
    line.reconciledWithType = "ReconciliationRecord"

    if status == "discrepancy":
        await _create_alert_if_not_already_active(db, line.tankId, "delivery_discrepancy", declaration.eventAt, discrepancy_value, tolerance_applied)
    elif status == "matched":
        resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_discrepancy", resolved_at=resolved_at)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_undeclared", resolved_at=resolved_at)
        await alerts_service.auto_resolve_alert(db, station_id=declaration.stationId, tank_id=line.tankId, product_id=None, alert_type="delivery_declaration_pending", resolved_at=resolved_at)

    await db.commit()
    await db.refresh(record)
    return ReconciliationRecordResponse.model_validate(record)


async def _sweep_stale_pending_delivery_declarations(db: AsyncSession, station_id: uuid.UUID) -> None:
    """Signale (alerte `delivery_declaration_pending`, plus légère qu'un
    écart avéré) toute LIGNE de livraison de cette station toujours
    `pending` (aucune détection trouvée sur sa cuve) après la fenêtre de
    tolérance étendue — appelé en best-effort depuis les deux points de
    déclenchement automatique (mission « flux de livraison station »),
    jamais depuis un scheduler dédié (aucun n'existe dans ce backend, cf.
    audit). Refonte 2026-09-17 : par ligne (cuve précise), plus par
    déclaration entière — une déclaration multi-cuves peut avoir une ligne
    rapprochée et une autre encore en attente."""
    stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=RECONCILIATION_DELIVERY_STALE_PENDING_HOURS_DEFAULT)
    rows_result = await db.execute(
        select(DeliveryDeclarationLine, DeliveryDeclaration.eventAt)
        .join(DeliveryDeclaration, DeliveryDeclaration.id == DeliveryDeclarationLine.declarationId)
        .join(ReconciliationRecord, ReconciliationRecord.id == DeliveryDeclarationLine.reconciledWithId)
        .where(
            DeliveryDeclaration.stationId == station_id,
            ReconciliationRecord.status == "pending",
            DeliveryDeclaration.eventAt < stale_before,
        )
    )
    for line, event_at in rows_result.all():
        await _create_alert_if_not_already_active(db, line.tankId, "delivery_declaration_pending", event_at, None, None)
    await db.commit()


async def _reverse_match_delivery_detected(db: AsyncSession, detected: DeliveryDetected, tank: Tank) -> None:
    """Retour de rapprochement depuis une détection nouvellement créée
    (mission « flux de livraison station », sens inverse de la fonction
    ci-dessus) : cherche une LIGNE de déclaration non encore appariée sur
    CETTE cuve précise dans la même fenêtre (refonte 2026-09-17 — bien plus
    précis que l'ancien filtre station+produit, qui pouvait apparier la
    mauvaise cuve quand plusieurs cuves du même produit recevaient en même
    temps) ; si trouvée, relance le rapprochement de sa déclaration (qui
    trouvera maintenant cette détection) ; sinon, la livraison physique n'a
    aucune trace administrative — alerte `delivery_undeclared`, le cas
    explicitement désigné comme le plus important à signaler."""
    settings = await _get_reconciliation_settings(db, tank.stationId)
    window_hours = _tolerance(settings, "deliveryWindowHours", RECONCILIATION_DELIVERY_WINDOW_HOURS_DEFAULT)
    window_start = detected.startTime - timedelta(hours=window_hours)
    window_end = detected.startTime + timedelta(hours=window_hours)

    candidates_result = await db.execute(
        select(DeliveryDeclarationLine)
        .join(DeliveryDeclaration, DeliveryDeclaration.id == DeliveryDeclarationLine.declarationId)
        .where(
            DeliveryDeclarationLine.tankId == tank.id,
            DeliveryDeclaration.eventAt >= window_start,
            DeliveryDeclaration.eventAt <= window_end,
        )
    )
    best_line, best_delta, best_declaration = None, None, None
    for candidate_line in candidates_result.scalars().all():
        declaration = await db.get(DeliveryDeclaration, candidate_line.declarationId)
        delta = abs((declaration.eventAt - detected.startTime).total_seconds())
        if best_delta is None or delta < best_delta:
            best_line, best_delta, best_declaration = candidate_line, delta, declaration

    if best_line is not None:
        await _evaluate_delivery_declaration_line_reconciliation_core(db, best_declaration, best_line)
        return

    await _create_alert_if_not_already_active(db, tank.id, "delivery_undeclared", detected.startTime, detected.volumeLiters, None)
    await db.commit()


async def evaluate_manual_gauging_declaration_reconciliation(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> ReconciliationRecordResponse:
    """Jaugeage manuel <-> `TankMeasurement` la plus proche dans le temps
    (Phase 5 §4, Phase 6 §4.1) — jamais un remplacement de la télémétrie."""
    declaration = await _get_declaration_or_404(db, ManualGaugingDeclaration, organization_id, declaration_id)
    station = await db.get(Station, declaration.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_READ)

    settings = await _get_reconciliation_settings(db, declaration.stationId)
    tolerance = _tolerance(settings, "gaugingHeightToleranceMm", RECONCILIATION_GAUGING_HEIGHT_TOLERANCE_MM_DEFAULT)

    sensor_ids_result = await db.execute(
        select(TankSensorMapping.hkSensorId).where(TankSensorMapping.tankId == declaration.tankId, TankSensorMapping.measurementType == "product_level")
    )
    sensor_ids = [row[0] for row in sensor_ids_result.all()]
    nearest = None
    if sensor_ids:
        # Recherche dans une fenêtre large (±24h) puis choix du plus proche en Python —
        # évite une expression de tri fragile sur un intervalle SQL cross-dialecte.
        search_start = declaration.eventAt - timedelta(hours=24)
        search_end = declaration.eventAt + timedelta(hours=24)
        measurements_result = await db.execute(
            select(TankMeasurement).where(
                TankMeasurement.hkSensorId.in_(sensor_ids), TankMeasurement.measuredAt >= search_start, TankMeasurement.measuredAt <= search_end
            )
        )
        best_delta = None
        for m in measurements_result.scalars().all():
            delta = abs((m.measuredAt - declaration.eventAt).total_seconds())
            if best_delta is None or delta < best_delta:
                nearest, best_delta = m, delta

    counterpart_type: str | None = None
    counterpart_id: str | None = None
    discrepancy_value: float | None = None
    tolerance_applied: float | None = None
    if nearest is None:
        status = "pending"
    else:
        counterpart_type, counterpart_id = "TankMeasurement", str(nearest.id)
        discrepancy_value = abs(float(declaration.declaredHeightMm) - float(nearest.rawValue))
        tolerance_applied = tolerance
        status = "matched" if discrepancy_value <= tolerance_applied else "discrepancy"

    record = await _record_reconciliation(
        db, "ManualGaugingDeclaration", declaration.id, counterpart_type, counterpart_id,
        "quantitative", status, discrepancy_value, "mm" if discrepancy_value is not None else None, tolerance_applied,
    )
    declaration.reconciledWithId = record.id
    declaration.reconciledWithType = "ReconciliationRecord"
    await db.commit()
    await db.refresh(record)
    return ReconciliationRecordResponse.model_validate(record)


async def evaluate_quality_check_declaration_reconciliation(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, declaration_id: uuid.UUID) -> ReconciliationRecordResponse:
    """Contrôle qualité/eau <-> présence d'une `Alert` type `water` sur la
    même cuve dans la fenêtre (Phase 5 §4) — une présence/absence, jamais un
    écart numérique : l'absence d'alerte ne prouve jamais que la
    déclaration est fausse, seulement que le capteur ne l'a pas détectée à
    son propre seuil."""
    declaration = await _get_declaration_or_404(db, QualityCheckDeclaration, organization_id, declaration_id)
    station = await db.get(Station, declaration.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_READ)

    settings = await _get_reconciliation_settings(db, declaration.stationId)
    window_hours = _tolerance(settings, "qualityCheckWindowHours", RECONCILIATION_QUALITY_CHECK_WINDOW_HOURS_DEFAULT)
    window_start = declaration.eventAt - timedelta(hours=window_hours)
    window_end = declaration.eventAt + timedelta(hours=window_hours)

    # Jamais de requête directe sur `Alert` (capacité partagée) depuis ici —
    # `find_alert_in_window` est le point d'entrée public d'Alerts pour ce
    # besoin de lecture (présence/absence dans une fenêtre).
    alert = await alerts_service.find_alert_in_window(
        db, tank_id=declaration.tankId, alert_type="water", window_start=window_start, window_end=window_end
    )

    if declaration.waterDetected and alert is not None:
        status, counterpart_type, counterpart_id = "matched", "Alert", str(alert.id)
    elif not declaration.waterDetected and alert is None:
        status, counterpart_type, counterpart_id = "matched", None, None
    elif alert is not None:
        status, counterpart_type, counterpart_id = "discrepancy", "Alert", str(alert.id)
    else:
        status, counterpart_type, counterpart_id = "discrepancy", None, None

    record = await _record_reconciliation(db, "QualityCheckDeclaration", declaration.id, counterpart_type, counterpart_id, "quantitative", status, None, None, None)
    declaration.reconciledWithId = record.id
    declaration.reconciledWithType = "ReconciliationRecord"
    await db.commit()
    await db.refresh(record)
    return ReconciliationRecordResponse.model_validate(record)


async def _compute_stock_reconciliation(db: AsyncSession, tank: Tank, day: date) -> dict:
    """Calcul pur (aucune vérification de permission, aucun effet de bord)
    partagé par `evaluate_stock_reconciliation` (déclenchement manuel/à la
    demande, Phase 4 v2 §6) et `_trigger_stock_discrepancy_alert`
    (déclenchement automatique à la déclaration d'une vente, mission
    détection de pertes phase 2, 2026-09-18) — un seul calcul, deux moments
    d'intention différents, jamais deux implémentations divergentes."""
    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)

    sales_result = await db.execute(
        select(func.coalesce(func.sum(Sale.quantityLiters), 0)).where(
            Sale.stationId == tank.stationId, Sale.fuelProductId == tank.fuelProductId, Sale.eventAt >= day_start, Sale.eventAt < day_end
        )
    )
    declared_volume = float(sales_result.scalar_one())

    cash_result = await _get_or_compute_tank_cash_for_day(db, tank, day_start, day_end)
    telemetric_volume = cash_result["volumeSoldLiters"]

    if telemetric_volume is None:
        status, discrepancy_value, tolerance_applied = "insufficient_data", None, None
    else:
        # Aucune tolérance dédiée proposée pour ce rapprochement (Phase 6 §6
        # ne couvre que les 4 tolérances opérationnelles) — repli explicite
        # sur la tolérance de livraison en pourcentage, seule déjà définie
        # pour un écart de volume, plutôt que d'inventer une nouvelle
        # constante non demandée par aucune phase antérieure.
        settings = await _get_reconciliation_settings(db, tank.stationId)
        percent_tolerance = _tolerance(settings, "deliveryVolumeTolerancePercent", RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_PERCENT_DEFAULT)
        tolerance_applied = abs(telemetric_volume) * percent_tolerance / 100
        discrepancy_value = abs(declared_volume - telemetric_volume)
        status = "matched" if discrepancy_value <= tolerance_applied else "discrepancy"

    return {
        "status": status,
        "declaredVolume": declared_volume,
        "telemetricVolume": telemetric_volume,
        "discrepancyValue": discrepancy_value,
        "toleranceApplied": tolerance_applied,
    }


async def evaluate_stock_reconciliation(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, tank_id: uuid.UUID, day: date) -> ReconciliationRecordResponse:
    """Rapprochements n°1 (agrégé) et n°6 (le plus robuste) de Phase 4 v2
    §6 — implémentation unique (Phase 6 §4.2 : même calcul, deux moments
    d'intention différents) : ventes déclarées sur la journée pour cette
    cuve, comparées à `TankCashDailyAggregate.volumeSoldLiters` (réutilisé
    tel quel, aucun nouveau calcul télémétrique)."""
    tank = await get_tank(db, organization_id, tank_id)
    station = await db.get(Station, tank.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, RECONCILIATION_READ)

    result = await _compute_stock_reconciliation(db, tank, day)
    subject_id = uuid.uuid5(uuid.NAMESPACE_URL, f"stock-reconciliation:{tank_id}:{day.isoformat()}")
    discrepancy_value = result["discrepancyValue"]

    record = await _record_reconciliation(
        db, "TankStockDay", subject_id, "TankCashDailyAggregate", f"{tank_id}:{day.isoformat()}",
        "quantitative", result["status"], discrepancy_value, "liters" if discrepancy_value is not None else None, result["toleranceApplied"],
    )

    # Mission détection de pertes phase 3 (2026-09-18) : « confirmation/
    # annulation automatique » — ce même calcul est aussi celui qui
    # confirme ou annule une alerte déjà ouverte quand il est redéclenché
    # PLUS TARD pour un jour déjà passé (consultation de la page « Écarts
    # de caisse », ou une nouvelle déclaration sur cette cuve un autre
    # jour). Aucune notion de "provisoire" séparée dans le modèle Alert :
    # c'est simplement le résultat du dernier calcul en date pour cette
    # cuve qui prévaut, exactement comme les autres alertes auto-vérifiables.
    try:
        await _apply_stock_discrepancy_alert(db, tank, result)
    except Exception:
        logger.exception("Échec de la confirmation/annulation de l'alerte stock_declared_discrepancy (tank=%s, day=%s)", tank.id, day)

    await db.commit()
    await db.refresh(record)
    return ReconciliationRecordResponse.model_validate(record)


async def _apply_stock_discrepancy_alert(db: AsyncSession, tank: Tank, result: dict) -> None:
    """Effet de bord partagé par `_trigger_stock_discrepancy_alert` (Phase 2
    — déclaration de vente) et `evaluate_stock_reconciliation` (Phase 3 —
    consultation/nouvelle vérification d'un jour déjà passé) : à partir d'un
    résultat déjà calculé par `_compute_stock_reconciliation`, ouvre/met à
    jour ou referme l'alerte `stock_declared_discrepancy`. Un seul calcul,
    un seul effet de bord, jamais deux implémentations divergentes.

    - "discrepancy" : ouvre/met à jour l'alerte (`upsert_active_alert`,
      jamais de construction directe d'`Alert`, cf. `.importlinter`).
    - "matched" : referme automatiquement une alerte encore ouverte, si son
      écart a disparu (`auto_resolve_alert` — la même mécanique que les
      autres alertes auto-vérifiables).
    - "insufficient_data" : ne rien faire — un capteur muet ne prouve ni
      n'infirme rien, jamais une fermeture ou une ouverture sur cette base."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if result["status"] == "discrepancy":
        await alerts_service.upsert_active_alert(
            db,
            station_id=tank.stationId,
            tank_id=tank.id,
            product_id=tank.fuelProductId,
            alert_type="stock_declared_discrepancy",
            triggered_at=now,
            triggered_value=result["discrepancyValue"],
            threshold_value=result["toleranceApplied"],
            source_type="TankStockDay",
            source_id=tank.id,
        )
    elif result["status"] == "matched":
        await alerts_service.auto_resolve_alert(
            db, station_id=tank.stationId, tank_id=tank.id, product_id=tank.fuelProductId,
            alert_type="stock_declared_discrepancy", resolved_at=now,
        )


async def _trigger_stock_discrepancy_alert(db: AsyncSession, tank: Tank, day: date) -> None:
    """Déclenché juste après chaque déclaration de vente réussie
    (`create_sale`/`bulk_import_sales`) — mission détection de pertes phase 2
    (2026-09-18) : jamais de tâche planifiée dans cette application (aucune
    n'existe), donc c'est l'événement de déclaration lui-même qui réveille
    la vérification, pas une horloge. Ne bloque jamais la déclaration de
    vente elle-même : les appelants entourent cet appel d'un try/except."""
    result = await _compute_stock_reconciliation(db, tank, day)
    await _apply_stock_discrepancy_alert(db, tank, result)
    await db.commit()


# ================================================================
# Mission « vente-maintenant-reglementation » — implémentation des Blocs
# 1 (extensions documentaires), 4 corrigé (ventes boutique), 5 (catalogue
# produits), 6 (Maintenance), 7 (Réglementation). Conventions reprises
# telles quelles de la couche Commercial/Documentaire déjà en production :
# `_check_org_scope` pour les entités à portée organisation, un helper de
# liste scopée par station (repris de `_list_declarations`) pour les
# entités à portée station.
# ================================================================


async def _list_station_scoped(
    db: AsyncSession,
    model_cls,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    read_permission: str,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    order_by_desc_column,
):
    """Même principe que `_list_declarations` (Phase 7 §1 du plan de
    mission : réutiliser le pattern de pagination déjà éprouvé), généralisé
    aux nouvelles entités à portée station qui ne sont pas des
    `DeclarationMixin`."""
    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, read_permission, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {read_permission}.", status_code=403)
    if station_id is not None and not sees_all and station_id not in visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {read_permission}.", status_code=403)

    stmt = select(model_cls).join(Station, Station.id == model_cls.stationId).where(Station.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(model_cls.stationId.in_(visible_station_ids))
    if station_id is not None:
        stmt = stmt.where(model_cls.stationId == station_id)
    stmt = stmt.order_by(order_by_desc_column.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    return list(result.scalars().all()), total or 0


# ----------------------------------------------------------------
# Bloc 5 — Catalogue de produits vendables
# ----------------------------------------------------------------


async def create_sellable_product(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateSellableProductRequest) -> SellableProductResponse:
    # Portée station si le produit est propre à une station (corrigé —
    # utilisait _check_org_scope à tort, incohérent avec le reste des
    # entités liées à une station, découvert en générant un scénario de
    # démo réel avec des gérants scopés station) ; portée organisation
    # entière seulement pour un produit réseau (stationId absent).
    if data.stationId is not None:
        station = await db.get(Station, data.stationId)
        if station is None or station.organizationId != organization_id:
            raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, SELLABLE_PRODUCT_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_MANAGE)
    product = SellableProduct(
        organizationId=organization_id,
        stationId=data.stationId,
        name=data.name,
        sku=data.sku,
        barcodeValue=data.barcodeValue,
        category=data.category,
        unitPriceAmount=data.unitPriceAmount,
        currencyId=data.currencyId,
        stockQuantity=data.stockQuantity,
        lowStockThreshold=data.lowStockThreshold,
        imageStorageReference=data.imageStorageReference,
    )
    db.add(product)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(code="barcode_already_used", message="Ce code-barres est déjà utilisé par un autre produit de cette organisation.", status_code=409)
    await db.refresh(product)
    return await _to_sellable_product_response(db, product, station_id=None)


async def update_sellable_product(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, product_id: uuid.UUID, data: UpdateSellableProductRequest) -> SellableProductResponse:
    product = await db.get(SellableProduct, product_id)
    if product is None or product.organizationId != organization_id:
        raise AppError(code="sellable_product_not_found", message="Produit introuvable.", status_code=404)
    if product.stationId is not None:
        station = await db.get(Station, product.stationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, SELLABLE_PRODUCT_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return await _to_sellable_product_response(db, product, station_id=product.stationId)


async def list_sellable_products(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None, search: str | None
) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_READ)
    stmt = select(SellableProduct).where(SellableProduct.organizationId == organization_id, SellableProduct.active == True)  # noqa: E712
    if station_id is not None:
        stmt = stmt.where((SellableProduct.stationId == station_id) | (SellableProduct.stationId.is_(None)))
    if search:
        like = f"%{search}%"
        stmt = stmt.where((SellableProduct.name.ilike(like)) | (SellableProduct.sku.ilike(like)) | (SellableProduct.barcodeValue == search))
    stmt = stmt.order_by(SellableProduct.name.asc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    data = [await _to_sellable_product_response(db, r, station_id=station_id) for r in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _to_sellable_product_response(db: AsyncSession, product: SellableProduct, station_id: uuid.UUID | None) -> SellableProductResponse:
    image_url = get_storage_backend().get_download_url(product.imageStorageReference) if product.imageStorageReference else None
    response = SellableProductResponse.model_validate(product).model_copy(update={"imageUrl": image_url})
    resolve_for_station = station_id if station_id is not None else product.stationId
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    price, reason = await _resolve_applicable_product_price(db, product.id, resolve_for_station, now)
    if price is not None:
        response.resolvedUnitPriceAmount = price.priceAmount
        response.resolvedCurrencyId = price.currencyId
    else:
        # Repli explicite sur le prix par défaut du produit — jamais un
        # None silencieux tant qu'un prix quelconque existe déjà.
        response.resolvedUnitPriceAmount = product.unitPriceAmount
        response.resolvedCurrencyId = product.currencyId
        response.priceNotCalculableReason = reason
    return response


async def _resolve_applicable_product_price(
    db: AsyncSession, sellable_product_id: uuid.UUID, station_id: uuid.UUID | None, at
) -> tuple[SellableProductPrice | None, str | None]:
    """Mirroir de `_resolve_applicable_price` (carburant) pour les produits
    boutique : priorité à la ligne propre à la station, repli sur le défaut
    réseau. `reason` n'est renseigné que si aucune ligne de prix explicite
    n'existe (l'appelant utilise alors `SellableProduct.unitPriceAmount`
    comme dernier repli, jamais un None pur)."""
    if station_id is not None:
        result = await db.execute(
            select(SellableProductPrice)
            .where(
                SellableProductPrice.stationId == station_id,
                SellableProductPrice.sellableProductId == sellable_product_id,
                SellableProductPrice.effectiveFrom <= at,
            )
            .order_by(SellableProductPrice.effectiveFrom.desc())
            .limit(1)
        )
        price = result.scalar_one_or_none()
        if price is not None:
            return price, None

    default_result = await db.execute(
        select(SellableProductPrice)
        .where(
            SellableProductPrice.stationId.is_(None),
            SellableProductPrice.sellableProductId == sellable_product_id,
            SellableProductPrice.effectiveFrom <= at,
        )
        .order_by(SellableProductPrice.effectiveFrom.desc())
        .limit(1)
    )
    default_price = default_result.scalar_one_or_none()
    if default_price is not None:
        return default_price, None
    return None, "no_price_history_entry"


async def _get_sellable_product_or_404(db: AsyncSession, organization_id: uuid.UUID, product_id: uuid.UUID) -> SellableProduct:
    product = await db.get(SellableProduct, product_id)
    if product is None or product.organizationId != organization_id:
        raise AppError(code="sellable_product_not_found", message="Produit introuvable.", status_code=404)
    return product


async def create_sellable_product_price(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, product_id: uuid.UUID, data: CreateSellableProductPriceRequest
) -> SellableProductPriceResponse:
    product = await _get_sellable_product_or_404(db, organization_id, product_id)
    station = await get_station(db, organization_id, data.stationId) if data.stationId is not None else None
    if station is not None:
        await _check_declaration_scope(db, organization_id, actor_user_id, station, SELLABLE_PRODUCT_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_MANAGE)

    effective_from = _to_naive_utc(data.effectiveFrom)

    if data.currencyId is not None:
        currency_result = await db.execute(select(Currency).where(Currency.id == data.currencyId))
        if currency_result.scalar_one_or_none() is None:
            raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
        currency_id = data.currencyId
    elif station is not None:
        currency = await _resolve_station_default_currency(db, station)
        currency_id = currency.id
    else:
        raise AppError(
            code="currency_required_for_network_default",
            message="currencyId est obligatoire pour un prix par défaut réseau (aucune station dont déduire une devise).",
            status_code=422,
        )

    existing_conditions = [
        SellableProductPrice.stationId.is_(None) if data.stationId is None else SellableProductPrice.stationId == data.stationId,
        SellableProductPrice.sellableProductId == product_id,
        SellableProductPrice.effectiveFrom == effective_from,
    ]
    if data.stationId is None:
        existing_conditions.append(SellableProductPrice.currencyId == currency_id)
    existing = await db.execute(select(SellableProductPrice).where(*existing_conditions))
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="price_conflict_same_period",
            message="Une ligne de prix existe déjà pour cette station, ce produit et cette date de début.",
            status_code=409,
        )

    price = SellableProductPrice(
        stationId=data.stationId,
        sellableProductId=product_id,
        currencyId=currency_id,
        priceAmount=data.priceAmount,
        costAmount=data.costAmount,
        effectiveFrom=effective_from,
        changeReason=data.changeReason,
        createdBy=actor_user_id,
    )
    db.add(price)
    await db.flush()

    scope_label = station.name if station is not None else "réseau (défaut)"
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.sellableProductPrice.create",
        entity_type="SellableProductPrice", entity_id=price.id,
        summary=f"Prix {product.name} défini ({scope_label}) : {data.priceAmount}",
        changes={"priceAmount": {"after": str(data.priceAmount)}, "effectiveFrom": str(effective_from)},
        scope_resource_type="station" if station is not None else None,
        scope_resource_id=station.id if station is not None else None,
    )
    await db.commit()
    await db.refresh(price)
    is_future = price.effectiveFrom > datetime.now(timezone.utc).replace(tzinfo=None)
    return SellableProductPriceResponse.model_validate(price).model_copy(update={"isFuture": is_future})


async def list_sellable_product_prices(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, product_id: uuid.UUID
) -> list[SellableProductPriceResponse]:
    product = await _get_sellable_product_or_404(db, organization_id, product_id)
    if product.stationId is not None:
        station = await db.get(Station, product.stationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, SELLABLE_PRODUCT_READ)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_READ)
    result = await db.execute(
        select(SellableProductPrice).where(SellableProductPrice.sellableProductId == product_id).order_by(SellableProductPrice.effectiveFrom.desc())
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return [
        SellableProductPriceResponse.model_validate(p).model_copy(update={"isFuture": p.effectiveFrom > now})
        for p in result.scalars().all()
    ]


async def update_sellable_product_price(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, price_id: uuid.UUID, data: UpdateSellableProductPriceRequest
) -> SellableProductPriceResponse:
    """Correction ciblée uniquement — jamais la période, la station ou le
    produit (même garantie que update_price_history)."""
    price = await db.get(SellableProductPrice, price_id)
    if price is None:
        raise AppError(code="sellable_product_price_not_found", message="Ligne de prix introuvable.", status_code=404)
    product = await _get_sellable_product_or_404(db, organization_id, price.sellableProductId)
    if price.stationId is not None:
        station = await db.get(Station, price.stationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, SELLABLE_PRODUCT_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, SELLABLE_PRODUCT_MANAGE)

    updates = data.model_dump(exclude_unset=True)
    if "currencyId" in updates and updates["currencyId"] is not None:
        currency_result = await db.execute(select(Currency).where(Currency.id == updates["currencyId"]))
        if currency_result.scalar_one_or_none() is None:
            raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
    before = {field: str(getattr(price, field)) for field in updates}
    for field, value in updates.items():
        setattr(price, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.sellableProductPrice.correct",
        entity_type="SellableProductPrice", entity_id=price.id,
        summary=f"Correction du prix {product.name}",
        changes={field: {"before": before[field], "after": str(value)} for field, value in updates.items()},
        scope_resource_type="station" if price.stationId is not None else None,
        scope_resource_id=price.stationId,
    )
    await db.commit()
    await db.refresh(price)
    return SellableProductPriceResponse.model_validate(price)


async def bulk_import_sellable_products(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: BulkImportSellableProductsRequest
) -> BulkImportSellableProductsResponse:
    """Dernière ligne de défense d'un import (le fichier a déjà été analysé
    et ses en-têtes/types vérifiés côté client via /import/xlsx générique) —
    chaque ligne est vérifiée et insérée indépendamment (savepoint) pour
    qu'une ligne invalide n'annule jamais les lignes valides du même fichier,
    tout en rapportant une erreur précise par ligne (jamais un rejet global
    opaque)."""
    created_count = 0
    errors: list[BulkImportRowError] = []
    station_cache: dict[uuid.UUID, Station | None] = {}
    currency_ids = {row.currencyId for row in data.rows}
    known_currencies = set(
        (await db.execute(select(Currency.id).where(Currency.id.in_(currency_ids)))).scalars().all()
    )

    for row in data.rows:
        if row.currencyId not in known_currencies:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Devise introuvable."))
            continue
        if row.stationId is not None:
            if row.stationId not in station_cache:
                candidate = await db.get(Station, row.stationId)
                station_cache[row.stationId] = candidate if candidate is not None and candidate.organizationId == organization_id else None
            station = station_cache[row.stationId]
            if station is None:
                errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Station introuvable dans cette organisation."))
                continue
            allowed = await user_has_permission(db, actor_user_id, organization_id, SELLABLE_PRODUCT_MANAGE, "station", station.id)
        else:
            allowed = await user_has_permission(db, actor_user_id, organization_id, SELLABLE_PRODUCT_MANAGE, None, None)
        if not allowed:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Permission manquante pour créer un produit sur cette portée."))
            continue

        try:
            async with db.begin_nested():
                db.add(
                    SellableProduct(
                        organizationId=organization_id,
                        stationId=row.stationId,
                        name=row.name,
                        sku=row.sku,
                        barcodeValue=row.barcodeValue,
                        category=row.category,
                        unitPriceAmount=row.unitPriceAmount,
                        currencyId=row.currencyId,
                        stockQuantity=row.stockQuantity,
                        lowStockThreshold=row.lowStockThreshold,
                    )
                )
        except IntegrityError:
            errors.append(BulkImportRowError(rowNumber=row.rowNumber, message="Code-barres déjà utilisé par un autre produit de cette organisation."))
            continue
        created_count += 1

    await db.commit()
    return BulkImportSellableProductsResponse(createdCount=created_count, errors=errors)


# ----------------------------------------------------------------
# Bloc 4 corrigé — Ventes de produits boutique (panier multi-lignes)
# ----------------------------------------------------------------


async def create_product_sale_transaction(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateProductSaleTransactionRequest
) -> ProductSaleTransactionResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    # Portée station (corrigé — utilisait _check_org_scope à tort, une vente
    # boutique a toujours lieu dans une station précise, comme Sale).
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PRODUCT_SALE_CREATE)

    total_amount = 0.0
    lines: list[ProductSaleLine] = []
    for line in data.lines:
        product = await db.get(SellableProduct, line.sellableProductId)
        if product is None or product.organizationId != organization_id:
            raise AppError(code="sellable_product_not_found", message="Produit introuvable dans le panier.", status_code=404)
        line_total = round(line.quantity * line.unitPriceAmount, 4)
        total_amount += line_total
        lines.append(ProductSaleLine(sellableProductId=line.sellableProductId, quantity=line.quantity, unitPriceAmount=line.unitPriceAmount, lineTotalAmount=line_total))

    if data.paymentMethod == "credit" and data.commercialAccountId is None:
        raise AppError(code="commercial_account_required", message="Un compte client est requis pour une vente à crédit.", status_code=422)

    transaction = ProductSaleTransaction(
        stationId=data.stationId,
        authorUserId=actor_user_id,
        eventAt=data.eventAt,
        currencyId=data.currencyId,
        paymentMethod=data.paymentMethod,
        totalAmount=round(total_amount, 4),
        commercialAccountId=data.commercialAccountId,
    )
    db.add(transaction)
    await db.flush()
    for line in lines:
        line.transactionId = transaction.id
        db.add(line)

    if data.paymentMethod == "credit":
        account = await _get_commercial_account_or_404(db, organization_id, data.commercialAccountId)
        db.add(
            Receivable(
                commercialAccountId=account.id,
                productSaleTransactionId=transaction.id,
                amount=transaction.totalAmount,
                currencyId=data.currencyId,
                status="open",
            )
        )

    # Stock simple (Phase 4 mission Boutique) : décrémentation atomique en
    # SQL (jamais lecture-puis-écriture côté Python) pour rester correcte
    # sous ventes concurrentes — la contrainte CHECK stockQuantity >= 0 est
    # le garde-fou final si deux ventes concurrentes visent le même produit.
    try:
        for line in lines:
            await db.execute(
                update(SellableProduct)
                .where(SellableProduct.id == line.sellableProductId)
                .values(stockQuantity=SellableProduct.stockQuantity - line.quantity)
                .execution_options(synchronize_session=False)
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(code="insufficient_stock", message="Stock insuffisant pour un ou plusieurs produits du panier.", status_code=409)
    await db.refresh(transaction)
    result = await db.execute(select(ProductSaleLine).where(ProductSaleLine.transactionId == transaction.id))
    transaction_lines = result.scalars().all()
    response = ProductSaleTransactionResponse.model_validate(transaction)
    response.lines = [ProductSaleLineResponse.model_validate(l) for l in transaction_lines]
    return response


async def cancel_product_sale_transaction(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, transaction_id: uuid.UUID) -> ProductSaleTransactionResponse:
    """Jamais de suppression physique (§13 de la mission : traçabilité des
    annulations) — statut seulement, l'audit log garde la trace de qui/quand."""
    transaction = await db.get(ProductSaleTransaction, transaction_id)
    if transaction is None:
        raise AppError(code="product_sale_transaction_not_found", message="Vente introuvable.", status_code=404)
    station = await db.get(Station, transaction.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, PRODUCT_SALE_CANCEL)
    if transaction.status == "cancelled":
        raise AppError(code="already_cancelled", message="Cette vente est déjà annulée.", status_code=409)
    transaction.status = "cancelled"
    transaction.cancelledAt = datetime.now(timezone.utc).replace(tzinfo=None)
    transaction.cancelledByUserId = actor_user_id

    # Symétrique de la décrémentation à la vente (stock simple, Phase 4
    # mission Boutique) : réincrémenter chaque ligne annulée.
    lines_result = await db.execute(select(ProductSaleLine).where(ProductSaleLine.transactionId == transaction.id))
    for line in lines_result.scalars().all():
        await db.execute(
            update(SellableProduct)
            .where(SellableProduct.id == line.sellableProductId)
            .values(stockQuantity=SellableProduct.stockQuantity + line.quantity)
            .execution_options(synchronize_session=False)
        )

    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.productSaleTransaction.cancel", entity_type="ProductSaleTransaction", entity_id=transaction.id,
        summary=f"Annulation de la vente boutique {transaction.id} (montant {transaction.totalAmount}).",
    )
    await db.commit()
    await db.refresh(transaction)
    return ProductSaleTransactionResponse.model_validate(transaction)


async def list_product_sale_transactions(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None
) -> Page:
    rows, total = await _list_station_scoped(db, ProductSaleTransaction, organization_id, actor_user_id, PRODUCT_SALE_READ, pagination, station_id, ProductSaleTransaction.eventAt)
    return Page(data=[ProductSaleTransactionResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


# ----------------------------------------------------------------
# Bloc 6 — Maintenance : Technicien, Équipement, Intervention
# ----------------------------------------------------------------


async def create_technician(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateTechnicianRequest) -> TechnicianResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TECHNICIAN_MANAGE)
    technician = Technician(organizationId=organization_id, name=data.name, company=data.company, contact=data.contact, linkedUserId=data.linkedUserId)
    db.add(technician)
    await db.commit()
    await db.refresh(technician)
    return TechnicianResponse.model_validate(technician)


async def list_technicians(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, TECHNICIAN_READ)
    stmt = select(Technician).where(Technician.organizationId == organization_id, Technician.active == True).order_by(Technician.name.asc())  # noqa: E712
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[TechnicianResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def create_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateEquipmentRequest) -> EquipmentResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    # Portée station (corrigé — utilisait _check_org_scope à tort, un
    # équipement appartient toujours à une station précise).
    await _check_declaration_scope(db, organization_id, actor_user_id, station, EQUIPMENT_MANAGE)
    equipment = Equipment(
        stationId=data.stationId, type=data.type, name=data.name, manufacturer=data.manufacturer,
        model=data.model, serialNumber=data.serialNumber, installedAt=data.installedAt, warrantyUntil=data.warrantyUntil,
    )
    db.add(equipment)
    await db.commit()
    await db.refresh(equipment)
    return EquipmentResponse.model_validate(equipment)


async def update_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, equipment_id: uuid.UUID, data: UpdateEquipmentRequest) -> EquipmentResponse:
    equipment = await db.get(Equipment, equipment_id)
    if equipment is None:
        raise AppError(code="equipment_not_found", message="Équipement introuvable.", status_code=404)
    station = await db.get(Station, equipment.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="equipment_not_found", message="Équipement introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, EQUIPMENT_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(equipment, field, value)
    await db.commit()
    await db.refresh(equipment)
    return EquipmentResponse.model_validate(equipment)


async def list_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_station_scoped(db, Equipment, organization_id, actor_user_id, EQUIPMENT_READ, pagination, station_id, Equipment.createdAt)
    return Page(data=[EquipmentResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


# ================================================================
# Centre administratif et opérationnel de la station — Sécurité
# (SecurityEquipment), Fournisseurs par station (StationSupplier), Finances
# (sous-ressource dédiée sur Station).
# ================================================================


async def create_security_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateSecurityEquipmentRequest) -> SecurityEquipmentResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, SECURITY_EQUIPMENT_MANAGE)
    instance = SecurityEquipment(
        stationId=data.stationId, category=data.category, label=data.label, lastControlAt=data.lastControlAt,
        nextControlDueAt=data.nextControlDueAt, conformityStatus=data.conformityStatus, notes=data.notes,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return SecurityEquipmentResponse.model_validate(instance)


async def update_security_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, security_equipment_id: uuid.UUID, data: UpdateSecurityEquipmentRequest) -> SecurityEquipmentResponse:
    instance = await db.get(SecurityEquipment, security_equipment_id)
    if instance is None:
        raise AppError(code="security_equipment_not_found", message="Équipement de sécurité introuvable.", status_code=404)
    station = await db.get(Station, instance.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="security_equipment_not_found", message="Équipement de sécurité introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, SECURITY_EQUIPMENT_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(instance, field, value)
    await db.commit()
    await db.refresh(instance)
    return SecurityEquipmentResponse.model_validate(instance)


async def list_security_equipment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_station_scoped(db, SecurityEquipment, organization_id, actor_user_id, SECURITY_EQUIPMENT_READ, pagination, station_id, SecurityEquipment.createdAt)
    return Page(data=[SecurityEquipmentResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


def _compute_contract_status(contract_end_date: date | None) -> str:
    """Même sémantique que `_compute_regulatory_document_status` (refonte
    page Fournisseurs) — jamais un statut saisi directement."""
    if contract_end_date is None:
        return "unknown"
    days_left = (contract_end_date - date.today()).days
    if days_left < 0:
        return "expired"
    if days_left <= 45:
        return "renew_soon"
    return "valid"


def _station_supplier_to_response(instance: StationSupplier) -> StationSupplierResponse:
    response = StationSupplierResponse.model_validate(instance)
    response.contractStatus = _compute_contract_status(instance.contractEndDate)
    return response


async def create_station_supplier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateStationSupplierRequest) -> StationSupplierResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_SUPPLIER_MANAGE)
    supplier = await _get_supplier_or_404(db, organization_id, data.supplierId)
    existing = await db.execute(
        select(StationSupplier).where(StationSupplier.stationId == data.stationId, StationSupplier.supplierId == data.supplierId)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        if not row.active:
            row.active = True
            for field, value in data.model_dump(exclude={"stationId", "supplierId"}).items():
                setattr(row, field, value)
            await record_audit_event(
                db, organization_id, actor_user_id,
                action="zyloLiquid.stationSupplier.reactivate", entity_type="StationSupplier", entity_id=row.id,
                summary=f"Réactivation du fournisseur {supplier.name} sur la station",
                scope_resource_type="station", scope_resource_id=station.id,
            )
            await db.commit()
            await db.refresh(row)
            return _station_supplier_to_response(row)
        raise AppError(code="station_supplier_already_linked", message="Ce fournisseur est déjà associé à cette station.", status_code=409)
    instance = StationSupplier(**data.model_dump())
    db.add(instance)
    await db.flush()
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationSupplier.create", entity_type="StationSupplier", entity_id=instance.id,
        summary=f"Ajout du fournisseur {supplier.name} à la station",
        scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(instance)
    return _station_supplier_to_response(instance)


async def update_station_supplier(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_supplier_id: uuid.UUID, data: UpdateStationSupplierRequest) -> StationSupplierResponse:
    instance = await db.get(StationSupplier, station_supplier_id)
    if instance is None:
        raise AppError(code="station_supplier_not_found", message="Association station/fournisseur introuvable.", status_code=404)
    station = await db.get(Station, instance.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_supplier_not_found", message="Association station/fournisseur introuvable.", status_code=404)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_SUPPLIER_MANAGE)
    supplier = await db.get(Supplier, instance.supplierId)
    updates = data.model_dump(exclude_unset=True)
    before = {field: getattr(instance, field) for field in updates}
    for field, value in updates.items():
        if value is not None:
            setattr(instance, field, value)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationSupplier.update", entity_type="StationSupplier", entity_id=instance.id,
        summary=f"Modification du fournisseur {supplier.name if supplier else '?'} sur la station",
        changes={field: {"before": str(before[field]), "after": str(updates[field])} for field in updates},
        scope_resource_type="station", scope_resource_id=station.id,
    )
    await db.commit()
    await db.refresh(instance)
    return _station_supplier_to_response(instance)


async def list_station_suppliers(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_station_scoped(db, StationSupplier, organization_id, actor_user_id, STATION_SUPPLIER_READ, pagination, station_id, StationSupplier.createdAt)
    data = [_station_supplier_to_response(r) for r in rows]
    return Page(data=data, meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


def _station_financial_response(station: Station) -> StationFinancialResponse:
    # `Station.id` (clé primaire) doit devenir `stationId` dans cette
    # sous-ressource — model_validate ne peut pas le dériver automatiquement
    # (il n'existe pas de colonne `stationId` sur Station elle-même).
    return StationFinancialResponse(
        stationId=station.id, taxId=station.taxId, billingAddress=station.billingAddress,
        costCenterCode=station.costCenterCode, bankAccountInfo=station.bankAccountInfo,
    )


async def get_station_financial(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> StationFinancialResponse:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_FINANCIAL_READ)
    return _station_financial_response(station)


async def update_station_financial(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, data: UpdateStationFinancialRequest) -> StationFinancialResponse:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_FINANCIAL_MANAGE)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(station, field, value)
    await db.commit()
    await db.refresh(station)
    return _station_financial_response(station)


# ================================================================
# Module Personnel — création de compte + profil de poste pour un membre du
# personnel d'une station (mockup emalioration/personnel/). Le rôle
# lui-même reste géré par le RBAC existant (assign_role), jamais dupliqué.
# ================================================================


def _station_staff_response(profile: StationStaffProfile, user: User) -> StationStaffResponse:
    photo_url = None
    if user.photoStorageReference:
        from app.shared.storage import get_storage_backend

        photo_url = get_storage_backend().get_download_url(user.photoStorageReference)
    return StationStaffResponse(
        id=profile.id, userId=user.id, organizationId=profile.organizationId,
        email=user.email, fullName=user.fullName, firstName=user.firstName, lastName=user.lastName,
        phone=user.phone, photoUrl=photo_url, status=user.status,
        employeeNumber=profile.employeeNumber, contractType=profile.contractType,
        assignedStationId=profile.assignedStationId, directManagerUserId=profile.directManagerUserId,
        assignedAt=profile.assignedAt,
    )


async def create_station_staff_member(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateStationStaffRequest) -> CreateStationStaffResponse:
    station = await get_station(db, organization_id, data.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_MANAGE)
    await check_email_available(db, data.email)

    # Mot de passe temporaire — généré côté serveur, jamais choisi par la
    # personne (aucune infrastructure d'invitation par email aujourd'hui,
    # décision validée avec le commanditaire). Affiché UNE SEULE fois dans
    # cette réponse, jamais stocké en clair, jamais rejoué ailleurs.
    temporary_password = secrets.token_urlsafe(9)
    full_name = f"{data.firstName} {data.lastName}".strip()
    user = build_user(
        email=data.email, full_name=full_name, hashed_password=hash_password(temporary_password),
        must_change_password=True, first_name=data.firstName, last_name=data.lastName, phone=data.phone,
    )
    if data.photoStorageReference:
        user.photoStorageReference = data.photoStorageReference
    db.add(user)
    await db.flush()

    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    profile = StationStaffProfile(
        organizationId=organization_id, userId=user.id, employeeNumber=data.employeeNumber,
        contractType=data.contractType, assignedStationId=data.stationId,
        directManagerUserId=data.directManagerUserId, assignedAt=date.today(),
    )
    db.add(profile)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationStaff.create", entity_type="User", entity_id=user.id,
        summary=f"Création du membre du personnel {full_name} ({data.email})",
        scope_resource_type="station", scope_resource_id=data.stationId,
    )
    await db.commit()
    await db.refresh(user)
    await db.refresh(profile)

    if data.roleId is not None:
        # Étape distincte, déjà auditée par `assign_role` lui-même — jamais
        # une logique d'assignation dupliquée ici.
        await assign_role(db, organization_id, actor_user_id, user.id, data.roleId, resource_type="station", resource_id=data.stationId)

    return CreateStationStaffResponse(staff=_station_staff_response(profile, user), temporaryPassword=temporary_password)


async def _get_station_staff_or_404(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> tuple[StationStaffProfile, User]:
    result = await db.execute(select(StationStaffProfile).where(StationStaffProfile.organizationId == organization_id, StationStaffProfile.userId == user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise AppError(code="station_staff_not_found", message="Membre du personnel introuvable.", status_code=404)
    user = await db.get(User, user_id)
    if user is None:
        raise AppError(code="station_staff_not_found", message="Membre du personnel introuvable.", status_code=404)
    return profile, user


async def update_station_staff_profile(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, user_id: uuid.UUID, data: UpdateStationStaffRequest) -> StationStaffResponse:
    profile, user = await _get_station_staff_or_404(db, organization_id, user_id)
    # Portée : la station ACTUELLEMENT affectée (avant modification) — un
    # gérant ne peut modifier que le personnel de sa propre station, y
    # compris pour le réaffecter ailleurs.
    if profile.assignedStationId is not None:
        station = await get_station(db, organization_id, profile.assignedStationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, STATION_STAFF_MANAGE)

    updates = data.model_dump(exclude_unset=True)
    name_changed = "firstName" in updates or "lastName" in updates
    for field in ("firstName", "lastName", "phone", "photoStorageReference"):
        if field in updates:
            setattr(user, field, updates.pop(field))
    if name_changed:
        # `fullName` reste le nom affiché ailleurs dans l'app (audit,
        # sélecteurs) — toujours recalculé depuis prénom/nom à jour.
        user.fullName = f"{user.firstName or ''} {user.lastName or ''}".strip() or user.fullName
    for field, value in updates.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    await db.refresh(user)
    return _station_staff_response(profile, user)


async def deactivate_station_staff_access(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, user_id: uuid.UUID) -> StationStaffResponse:
    profile, user = await _get_station_staff_or_404(db, organization_id, user_id)
    if profile.assignedStationId is not None:
        station = await get_station(db, organization_id, profile.assignedStationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, STATION_STAFF_MANAGE)
    user.status = "suspended"
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationStaff.deactivate", entity_type="User", entity_id=user.id,
        summary=f"Désactivation de l'accès de {user.fullName}",
        scope_resource_type="station", scope_resource_id=profile.assignedStationId,
    )
    await db.commit()
    await db.refresh(profile)
    await db.refresh(user)
    return _station_staff_response(profile, user)


async def change_station_staff_role(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, user_id: uuid.UUID, data: ChangeStationStaffRoleRequest
) -> StationStaffResponse:
    """Remplace l'attribution de rôle de ce membre du personnel, scopée à sa
    station d'affectation (mission « fiche Personnel — gestion des droits »,
    2026-09-16). Contourne volontairement les endpoints RBAC génériques
    (`POST /rbac/.../user-roles`), qui exigent `ROLE_MANAGE` organisation
    entière et sont donc inutilisables par un gérant de station — même
    pattern que `create_station_staff_member` : `assign_role` est appelé
    directement en tant que fonction de service, après vérification de
    `STATION_STAFF_MANAGE` scopée à la station. La protection anti-escalade
    de privilèges d'`assign_role` (`_assert_no_privilege_escalation`)
    s'applique sans changement : un gérant ne peut jamais attribuer un rôle
    plus puissant que le sien sur cette même station."""
    profile, user = await _get_station_staff_or_404(db, organization_id, user_id)
    if profile.assignedStationId is None:
        raise AppError(code="station_staff_not_assigned", message="Ce membre du personnel n'est rattaché à aucune station.", status_code=422)
    station = await get_station(db, organization_id, profile.assignedStationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_MANAGE)

    result = await db.execute(
        select(UserRole).where(
            UserRole.organizationId == organization_id,
            UserRole.userId == user_id,
            UserRole.resourceType == "station",
            UserRole.resourceId == profile.assignedStationId,
        )
    )
    for existing_assignment in result.scalars().all():
        await unassign_role(db, organization_id, actor_user_id, existing_assignment.id)

    await assign_role(db, organization_id, actor_user_id, user_id, data.roleId, resource_type="station", resource_id=profile.assignedStationId)
    await db.refresh(profile)
    await db.refresh(user)
    return _station_staff_response(profile, user)


async def reset_station_staff_password(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, user_id: uuid.UUID
) -> str:
    """Réinitialisation d'un mot de passe PAR UN TIERS (fiche Personnel) —
    distinct de `change_password` (libre-service, exige l'ancien mot de
    passe). Même mécanisme que la création d'un membre du personnel
    (`create_station_staff_member`) : mot de passe temporaire généré côté
    serveur, jamais choisi par la personne, retourné en clair une seule fois
    dans cette réponse, jamais stocké ni rejouable ensuite — force un
    changement via `POST /auth/change-password` à la prochaine connexion."""
    profile, user = await _get_station_staff_or_404(db, organization_id, user_id)
    if profile.assignedStationId is not None:
        station = await get_station(db, organization_id, profile.assignedStationId)
        await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_MANAGE)
    else:
        await _check_org_scope(db, organization_id, actor_user_id, STATION_STAFF_MANAGE)

    temporary_password = secrets.token_urlsafe(9)
    user.hashedPassword = hash_password(temporary_password)
    user.mustChangePassword = True
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.stationStaff.passwordReset", entity_type="User", entity_id=user.id,
        summary=f"Réinitialisation du mot de passe de {user.fullName}",
        scope_resource_type="station", scope_resource_id=profile.assignedStationId,
    )
    await db.commit()
    return temporary_password


async def list_station_staff_profiles(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> list[StationStaffResponse]:
    station = await get_station(db, organization_id, station_id)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, STATION_STAFF_READ)
    result = await db.execute(
        select(StationStaffProfile, User)
        .join(User, User.id == StationStaffProfile.userId)
        .where(StationStaffProfile.organizationId == organization_id, StationStaffProfile.assignedStationId == station_id)
        .order_by(User.fullName)
    )
    return [_station_staff_response(profile, user) for profile, user in result.all()]


async def create_intervention(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateInterventionRequest) -> InterventionResponse:
    equipment = await db.get(Equipment, data.equipmentId)
    if equipment is None or equipment.stationId != data.stationId:
        raise AppError(code="equipment_not_found", message="Équipement introuvable pour cette station.", status_code=404)
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    # Portée station (corrigé — utilisait _check_org_scope à tort).
    await _check_declaration_scope(db, organization_id, actor_user_id, station, INTERVENTION_CREATE)
    intervention = Intervention(
        equipmentId=data.equipmentId, stationId=data.stationId, priority=data.priority, type=data.type,
        description=data.description, plannedAt=data.plannedAt, linkedAlertId=data.linkedAlertId,
        openedAt=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(intervention)
    await db.commit()
    await db.refresh(intervention)
    return InterventionResponse.model_validate(intervention)


async def assign_intervention(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, intervention_id: uuid.UUID, data: AssignInterventionRequest) -> InterventionResponse:
    intervention = await db.get(Intervention, intervention_id)
    if intervention is None:
        raise AppError(code="intervention_not_found", message="Intervention introuvable.", status_code=404)
    station = await db.get(Station, intervention.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, INTERVENTION_ASSIGN)
    technician = await db.get(Technician, data.technicianId)
    if technician is None or technician.organizationId != organization_id:
        raise AppError(code="technician_not_found", message="Technicien introuvable.", status_code=404)
    intervention.technicianId = data.technicianId
    if intervention.status == "planned":
        intervention.status = "in_progress"
    await db.commit()
    await db.refresh(intervention)
    return InterventionResponse.model_validate(intervention)


async def close_intervention(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, intervention_id: uuid.UUID, data: CloseInterventionRequest) -> InterventionResponse:
    """Reprend directement le gate de permission déjà présent dans la
    maquette prototype (`peutModifier("Maintenance", ...)`, Phase 1 §0 du
    plan de mission) — action volontairement plus restreinte que la simple
    consultation."""
    intervention = await db.get(Intervention, intervention_id)
    if intervention is None:
        raise AppError(code="intervention_not_found", message="Intervention introuvable.", status_code=404)
    station = await db.get(Station, intervention.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, INTERVENTION_CLOSE)
    if intervention.status == "closed":
        raise AppError(code="intervention_already_closed", message="Cette intervention est déjà clôturée.", status_code=409)
    intervention.status = "closed"
    intervention.closedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    intervention.diagnosis = data.diagnosis
    intervention.actionTaken = data.actionTaken
    intervention.cost = data.cost
    equipment = await db.get(Equipment, intervention.equipmentId)
    if equipment is not None:
        equipment.lastMaintenanceAt = date.today()
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.intervention.close", entity_type="Intervention", entity_id=intervention.id,
        summary=f"Clôture de l'intervention {intervention.id}.",
    )
    await db.commit()
    await db.refresh(intervention)
    return InterventionResponse.model_validate(intervention)


async def list_interventions(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_station_scoped(db, Intervention, organization_id, actor_user_id, INTERVENTION_READ, pagination, station_id, Intervention.openedAt)
    return Page(data=[InterventionResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


# ----------------------------------------------------------------
# Bloc 7 — Réglementation
# ----------------------------------------------------------------


def _compute_regulatory_document_status(expires_at: date | None) -> str:
    """Statut toujours calculé depuis l'échéance, jamais saisi directement
    (Phase 4 §3.1 du plan de mission)."""
    if expires_at is None:
        return "unknown"
    days_left = (expires_at - date.today()).days
    if days_left < 0:
        return "expired"
    if days_left <= 45:
        return "renew_soon"
    return "valid"


async def _regulatory_document_to_response(db: AsyncSession, document: RegulatoryDocument) -> RegulatoryDocumentResponse:
    response = RegulatoryDocumentResponse.model_validate(document)
    response.computedStatus = _compute_regulatory_document_status(document.expiresAt)
    if document.responsibleUserId is not None:
        responsible = await db.get(User, document.responsibleUserId)
        if responsible is not None:
            response.responsibleUserName = responsible.fullName
            response.responsibleUserEmail = responsible.email
    return response


async def create_regulatory_document(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateRegulatoryDocumentRequest) -> RegulatoryDocumentResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    # Portée station (corrigé — utilisait _check_org_scope à tort).
    await _check_declaration_scope(db, organization_id, actor_user_id, station, REGULATORY_DOCUMENT_CREATE)
    document = RegulatoryDocument(
        stationId=data.stationId, documentType=data.documentType, authority=data.authority,
        issuedAt=data.issuedAt, expiresAt=data.expiresAt, sourceReference=data.sourceReference, certaintyLevel=data.certaintyLevel,
        notes=data.notes, responsibleUserId=data.responsibleUserId,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return await _regulatory_document_to_response(db, document)


async def renew_regulatory_document(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, document_id: uuid.UUID, data: CreateRegulatoryDocumentRequest) -> RegulatoryDocumentResponse:
    """Renouvellement = nouveau `RegulatoryDocument` chaîné via
    `supersededByDocumentId` (Phase 5 §3 du plan de mission : jamais
    réécrire, toujours ajouter — même principe que le versionnement
    documentaire)."""
    old_document = await db.get(RegulatoryDocument, document_id)
    if old_document is None:
        raise AppError(code="regulatory_document_not_found", message="Document réglementaire introuvable.", status_code=404)
    station = await db.get(Station, old_document.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, REGULATORY_DOCUMENT_MANAGE)
    new_document = RegulatoryDocument(
        stationId=old_document.stationId, documentType=data.documentType, authority=data.authority,
        issuedAt=data.issuedAt, expiresAt=data.expiresAt, sourceReference=data.sourceReference, certaintyLevel=data.certaintyLevel,
        notes=data.notes, responsibleUserId=data.responsibleUserId,
    )
    db.add(new_document)
    await db.flush()
    old_document.supersededByDocumentId = new_document.id
    await db.commit()
    await db.refresh(new_document)
    return await _regulatory_document_to_response(db, new_document)


async def update_regulatory_document(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, document_id: uuid.UUID, data: UpdateRegulatoryDocumentRequest
) -> RegulatoryDocumentResponse:
    """Correction de métadonnées (autorité, référence, notes, responsable) —
    jamais les dates ni le type, qui passent par `renew_regulatory_document`
    (refonte onglet Réglementation)."""
    document = await db.get(RegulatoryDocument, document_id)
    if document is None:
        raise AppError(code="regulatory_document_not_found", message="Document réglementaire introuvable.", status_code=404)
    station = await db.get(Station, document.stationId)
    await _check_declaration_scope(db, organization_id, actor_user_id, station, REGULATORY_DOCUMENT_MANAGE)
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(document, field, value)
    await db.commit()
    await db.refresh(document)
    return await _regulatory_document_to_response(db, document)


async def list_regulatory_documents(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None, needs_action_only: bool
) -> Page:
    """`needs_action_only` reprend la vue par défaut décidée en Phase 4 §3.1
    du plan de mission ("nécessitant une action" plutôt que la liste
    exhaustive, seule façon de rester exploitable à grande échelle)."""
    rows, total = await _list_station_scoped(db, RegulatoryDocument, organization_id, actor_user_id, REGULATORY_DOCUMENT_READ, pagination, station_id, RegulatoryDocument.expiresAt)
    if needs_action_only:
        rows = [r for r in rows if _compute_regulatory_document_status(r.expiresAt) in ("expired", "renew_soon")]
    data = [await _regulatory_document_to_response(db, r) for r in rows]
    return Page(data=data, meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


async def create_regulatory_declaration(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateRegulatoryDeclarationRequest) -> RegulatoryDeclarationResponse:
    station = await db.get(Station, data.stationId)
    if station is None or station.organizationId != organization_id:
        raise AppError(code="station_not_found", message="Station introuvable.", status_code=404)
    # Portée station (corrigé — utilisait _check_org_scope à tort).
    await _check_declaration_scope(db, organization_id, actor_user_id, station, REGULATORY_DOCUMENT_CREATE)
    declaration = RegulatoryDeclaration(
        stationId=data.stationId, type=data.type, authority=data.authority,
        triggerIncidentId=data.triggerIncidentId, reserve=data.reserve,
    )
    db.add(declaration)
    await db.commit()
    await db.refresh(declaration)
    return RegulatoryDeclarationResponse.model_validate(declaration)


async def list_regulatory_declarations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, station_id: uuid.UUID | None) -> Page:
    rows, total = await _list_station_scoped(db, RegulatoryDeclaration, organization_id, actor_user_id, REGULATORY_DECLARATION_READ, pagination, station_id, RegulatoryDeclaration.createdAt)
    return Page(data=[RegulatoryDeclarationResponse.model_validate(r) for r in rows], meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset))


