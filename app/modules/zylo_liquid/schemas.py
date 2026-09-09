import colorsys
import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# Reflète exactement ck_zlSale_paymentMethod / ck_zlProductSaleTransaction_paymentMethod
# (app/modules/zylo_liquid/models.py) — élargi mission
# « vente-maintenant-reglementation » Bloc 3 (mobile money, Phase 2 §2 de la
# mission : dominance confirmée d'Orange Money/MTN MoMo au Cameroun).
PAYMENT_METHODS = ("cash", "card", "fleet", "credit", "orange_money", "mtn_momo", "bank_transfer", "cheque", "other")


def _reject_reserved_red(value: str | None) -> str | None:
    """Le rouge est réservé à l'indicateur de stock bas (cuve au seuil bas,
    Tank.lowAlarmMm) — un produit ne peut jamais se l'approprier comme
    couleur d'affichage, sinon "barre rouge" perdrait sa signification
    unique à l'écran. Rejette toute teinte perçue comme rouge (pas
    seulement le rouge exact utilisé pour l'alerte), pour éviter les
    contournements par une nuance très proche."""
    if value is None:
        return value
    hex_value = value.lstrip("#")
    if len(hex_value) != 6:
        raise ValueError("displayColor doit être un code hexadécimal #RRGGBB.")
    try:
        r, g, b = (int(hex_value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise ValueError("displayColor doit être un code hexadécimal valide.") from exc
    hue, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue_deg = hue * 360
    is_reddish = saturation > 0.25 and 0.15 < lightness < 0.85 and (hue_deg <= 20 or hue_deg >= 340)
    if is_reddish:
        raise ValueError("Le rouge est réservé à l'indicateur de stock bas — choisissez une autre couleur pour ce produit.")
    return value


class CreateFuelProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=10)
    densityGPerCm3: float | None = None
    thermalExpansionCoefficient: float | None = None
    displayColor: str | None = Field(default=None, max_length=7)

    _validate_display_color = field_validator("displayColor")(_reject_reserved_red)


class UpdateFuelProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    densityGPerCm3: float | None = None
    thermalExpansionCoefficient: float | None = None
    displayColor: str | None = Field(default=None, max_length=7)
    active: bool | None = None

    _validate_display_color = field_validator("displayColor")(_reject_reserved_red)


class FuelProductResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    code: str
    densityGPerCm3: float | None
    thermalExpansionCoefficient: float | None
    displayColor: str | None
    active: bool

    model_config = {"from_attributes": True}


class CreateStationFuelProductRequest(BaseModel):
    stationId: uuid.UUID
    fuelProductId: uuid.UUID


class UpdateStationFuelProductRequest(BaseModel):
    active: bool


class StationFuelProductResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    active: bool
    minThresholdLiters: float | None = None
    criticalThresholdLiters: float | None = None
    safetyStockLiters: float | None = None

    model_config = {"from_attributes": True}


class UpdateStationFuelProductThresholdsRequest(BaseModel):
    minThresholdLiters: float | None = Field(default=None, ge=0)
    criticalThresholdLiters: float | None = Field(default=None, ge=0)
    safetyStockLiters: float | None = Field(default=None, ge=0)


class StationFuelProductOverviewResponse(BaseModel):
    """Ligne de la table « Carburants » (page Exploitation) — jointure
    StationFuelProduct + FuelProduct + agrégation des cuves de ce produit à
    cette station (jamais un stock/une capacité stockés en double) + dernier
    prix PriceHistory non-futur. `status` est calculé à partir du stock
    actuel et des seuils — 'inconnu' si aucun seuil n'a jamais été défini
    (jamais un statut inventé par défaut)."""

    id: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    fuelProductName: str
    fuelProductCode: str
    displayColor: str | None
    active: bool
    minThresholdLiters: float | None
    criticalThresholdLiters: float | None
    safetyStockLiters: float | None
    capacityLiters: float
    currentVolumeLiters: float | None
    status: str
    currentPriceAmount: float | None
    currencyCode: str | None
    priceEffectiveFrom: datetime | None

    model_config = {"from_attributes": True}


def _validate_closed_weekdays(value: str | None) -> str | None:
    """CSV de jours ISO (1=lundi..7=dimanche), ex. "7" ou "6,7". `None`/chaîne
    vide = ouvert tous les jours. Normalisé (dédoublonné, trié) pour que deux
    saisies équivalentes ("7,6" et "6,7") produisent la même valeur stockée."""
    if value is None or value.strip() == "":
        return None
    parts = [p.strip() for p in value.split(",") if p.strip() != ""]
    days: set[int] = set()
    for p in parts:
        if not p.isdigit() or not (1 <= int(p) <= 7):
            raise ValueError("closedWeekdays doit être une liste de jours ISO (1=lundi..7=dimanche) séparés par des virgules.")
        days.add(int(p))
    return ",".join(str(d) for d in sorted(days))


class CreateStationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=20)
    cityId: uuid.UUID | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "Africa/Douala"
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=200)
    openingTime: str = "06:00"
    closingTime: str = "22:00"
    is24h: bool = False
    closedWeekdays: str | None = None
    notes: str | None = None
    currencyOverrideId: uuid.UUID | None = None
    # Champs commerce/amenities — présents sur le modèle Station depuis le
    # début (phase-1-database.md §5) mais jamais exposés par aucun schéma
    # jusqu'ici (Centre administratif et opérationnel de la station, domaines
    # Exploitation/Infrastructure).
    exploitationType: str = Field(default="propre", max_length=20)
    hasShop: bool = False
    shopName: str | None = Field(default=None, max_length=120)
    shopSurfaceM2: float | None = None
    hasLavage: bool = False
    hasVidange: bool = False
    hasGazDomestique: bool = False
    nbPistes: int | None = Field(default=None, ge=0)
    surfaceTotaleM2: float | None = None

    _validate_closed_weekdays = field_validator("closedWeekdays")(_validate_closed_weekdays)


class UpdateStationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    cityId: uuid.UUID | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=200)
    openingTime: str | None = None
    closingTime: str | None = None
    is24h: bool | None = None
    closedWeekdays: str | None = None
    notes: str | None = None
    currencyOverrideId: uuid.UUID | None = None
    exploitationType: str | None = Field(default=None, max_length=20)
    hasShop: bool | None = None
    shopName: str | None = Field(default=None, max_length=120)
    shopSurfaceM2: float | None = None
    hasLavage: bool | None = None
    hasVidange: bool | None = None
    hasGazDomestique: bool | None = None
    nbPistes: int | None = Field(default=None, ge=0)
    surfaceTotaleM2: float | None = None

    _validate_closed_weekdays = field_validator("closedWeekdays")(_validate_closed_weekdays)


class StationResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    code: str
    cityId: uuid.UUID | None
    address: str | None
    latitude: float | None
    longitude: float | None
    timezone: str
    phone: str | None
    email: str | None
    openingTime: str
    closingTime: str
    is24h: bool
    closedWeekdays: str | None = None
    status: str
    integrationDate: date | None
    notes: str | None
    activeTankCount: int = 0
    currencyOverrideId: uuid.UUID | None = None
    exploitationType: str = "propre"
    hasShop: bool = False
    shopName: str | None = None
    shopSurfaceM2: float | None = None
    hasLavage: bool = False
    hasVidange: bool = False
    hasGazDomestique: bool = False
    nbPistes: int | None = None
    surfaceTotaleM2: float | None = None

    model_config = {"from_attributes": True}


class CreateTankRequest(BaseModel):
    stationId: uuid.UUID
    tankNumber: int = Field(gt=0)
    displayName: str = Field(min_length=1, max_length=100)
    capacityLiters: float = Field(gt=0)
    tankHeightMm: float = Field(gt=0)
    fuelProductId: uuid.UUID | None = None
    newFuelProductName: str | None = Field(default=None, min_length=1, max_length=100)
    newFuelProductCode: str | None = Field(default=None, min_length=1, max_length=10)
    heightAlarmMm: float = Field(gt=0)
    heightAlertMm: float = Field(gt=0)
    lowAlarmMm: float = Field(gt=0)
    alertWaterMaxMm: float = 25.00
    dataSourceType: str = "console"


class UpdateTankRequest(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=100)
    capacityLiters: float | None = Field(default=None, gt=0)
    calibratedCapacityLiters: float | None = None
    tankHeightMm: float | None = Field(default=None, gt=0)
    heightAlarmMm: float | None = None
    heightAlertMm: float | None = None
    lowAlarmMm: float | None = None
    alertWaterMaxMm: float | None = None
    active: bool | None = None
    notes: str | None = None


class TankResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    tankNumber: int
    displayName: str
    capacityLiters: float
    calibratedCapacityLiters: float | None
    tankHeightMm: float | None
    dataSourceType: str
    heightAlarmMm: float
    heightAlertMm: float
    lowAlarmMm: float
    alertWaterMaxMm: float
    active: bool
    productSince: date | None
    notes: str | None

    model_config = {"from_attributes": True}


class CreateTankSensorMappingRequest(BaseModel):
    tankId: uuid.UUID
    hkSerialNumber: str = Field(min_length=1, max_length=100)
    measurementType: str = Field(pattern="^(product_level|water_level|temperature)$")


class HolykellSensorLiveState(BaseModel):
    """Dernier état connu d'un sensor côté registre Holykell (couche
    télémétrie, `zyloLiquidHolykellDeviceRegistry`) — la vérité *mesurée*,
    distincte de la vérité *déclarée* du mapping (`validFrom`/`validUntil`/
    `active`). La fraîcheur et la santé de la sonde se lisent ici
    (`hkLastSeenAt`, `hkLastStatus`, `lastValueAt`), jamais sur la ligne de
    mapping. Champs tous optionnels : un sensor inconnu du registre (ex.
    mapping importé sans découverte Holykell) renvoie `live: null`, pas un
    état inventé."""

    hkSerialNumber: str | None = None
    hkSensorName: str | None = None
    hkUnit: str | None = None
    hkReportCycleSec: int | None = None
    # 1 = OK, 0 = KO côté Holykell (check `ck_zlHolykellDevice_lastStatus`)
    hkLastStatus: int | None = None
    hkLastSeenAt: datetime | None = None
    lastValue: float | None = None
    lastValueAt: datetime | None = None
    syncFrom: datetime | None = None


class TankSensorMappingResponse(BaseModel):
    id: uuid.UUID
    hkSensorId: int
    tankId: uuid.UUID
    measurementType: str
    validFrom: datetime
    validUntil: datetime | None
    active: bool
    # Renseigné par `service.list_tank_sensor_mappings` (jointure registre) ;
    # `None` sur les réponses create/close, qui ne portent pas l'état live.
    live: HolykellSensorLiveState | None = None

    model_config = {"from_attributes": True}


class CalibrationPointInput(BaseModel):
    heightMm: float = Field(ge=0)
    volumeLiters: float = Field(ge=0)


class ReplaceTankCalibrationPointsRequest(BaseModel):
    points: list[CalibrationPointInput] = Field(min_length=1)


class TankCalibrationPointResponse(BaseModel):
    id: uuid.UUID
    tankId: uuid.UUID
    heightMm: float
    volumeLiters: float

    model_config = {"from_attributes": True}


class ReplaceTankCalibrationPointsResponse(BaseModel):
    tankId: uuid.UUID
    pointCount: int
    points: list[TankCalibrationPointResponse]


class TankCurrentStateResponse(BaseModel):
    tankId: uuid.UUID
    tankNumber: int
    displayName: str
    sensorStatus: str  # "online" | "offline" | "not_configured"
    heightMm: float | None
    volumeLiters: float | None
    volumeNotCalculableReason: str | None
    volumeLiters15C: float | None
    sellableVolumeLiters: float | None
    waterHeightMm: float | None
    waterVolumeLiters: float | None
    temperatureC: float | None
    emptyVolumeLiters: float | None
    lastMeasurementAt: datetime | None
    monetaryValue: float | None = None
    currencyCode: str | None = None
    monetaryValueNotCalculableReason: str | None = None
    unitPriceAmount: float | None = None


class StationCurrentStateResponse(BaseModel):
    stationId: uuid.UUID
    tanks: list[TankCurrentStateResponse]


class TankMeasurementResponse(BaseModel):
    id: int
    measuredAt: datetime
    rawValue: float
    unit: str | None
    volumeLiters: float | None
    isCorrection: bool

    model_config = {"from_attributes": True}


class NetworkSummaryProductLine(BaseModel):
    fuelProductId: uuid.UUID
    fuelProductName: str
    totalVolumeLiters: float
    stationCount: int
    tankCount: int
    totalMonetaryValue: float | None = None
    currencyCode: str | None = None
    monetaryValueNotCalculableReason: str | None = None


class NetworkSummaryResponse(BaseModel):
    products: list[NetworkSummaryProductLine]
    totalVolumeLiters: float
    totalStationCount: int
    totalTankCount: int


class DeliveryDetectedResponse(BaseModel):
    id: uuid.UUID
    tankId: uuid.UUID
    stationId: uuid.UUID
    startTime: datetime
    startHeightMm: float
    endTime: datetime
    endHeightMm: float
    volumeLiters: float | None

    model_config = {"from_attributes": True}


class DeliveryInProgressResponse(BaseModel):
    """Montée en cours, pas encore confirmée — jamais persistée, recalculée
    à chaque appel (voir detect_delivery_in_progress). `startVolumeLiters`
    est le volume déjà présent dans la cuve avant le début de la hausse,
    `currentVolumeLiters` le volume actuel — la différence est le volume
    déjà entré, en temps réel."""

    tankId: uuid.UUID
    stationId: uuid.UUID
    startTime: datetime
    startHeightMm: float
    startVolumeLiters: float | None
    currentTime: datetime
    currentHeightMm: float
    currentVolumeLiters: float | None


class LeakEventResponse(BaseModel):
    id: uuid.UUID
    tankId: uuid.UUID
    stationId: uuid.UUID
    startTime: datetime
    endTime: datetime
    leakRateLph: float | None
    result: str

    model_config = {"from_attributes": True}


class ResolveAlertRequest(BaseModel):
    resolutionNote: str | None = None


class AlertResponse(BaseModel):
    id: uuid.UUID
    tankId: uuid.UUID
    stationId: uuid.UUID
    type: str
    status: str
    triggeredAt: datetime
    triggeredValue: float | None
    thresholdValue: float | None
    resolvedAt: datetime | None
    resolutionNote: str | None

    model_config = {"from_attributes": True}


class CreatePriceHistoryRequest(BaseModel):
    # None = prix par défaut réseau (audit Configuration carburant P2 §E) —
    # currencyId devient alors obligatoire (rien à dériver d'une station).
    stationId: uuid.UUID | None = None
    fuelProductId: uuid.UUID
    priceAmount: float = Field(gt=0)
    costAmount: float | None = Field(default=None, ge=0)
    currencyId: uuid.UUID | None = None
    effectiveFrom: datetime
    changeReason: str | None = None


class UpdatePriceHistoryRequest(BaseModel):
    priceAmount: float | None = Field(default=None, gt=0)
    costAmount: float | None = Field(default=None, ge=0)
    currencyId: uuid.UUID | None = None
    changeReason: str | None = None


class PriceHistoryResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID | None
    fuelProductId: uuid.UUID
    currencyId: uuid.UUID
    priceAmount: float
    costAmount: float | None
    effectiveFrom: datetime
    changeReason: str | None
    createdBy: uuid.UUID
    isFuture: bool = False

    model_config = {"from_attributes": True}


class HolykellAccountSyncStatusResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    lastSyncAt: datetime | None
    lastSyncStatus: str | None
    lastSyncError: str | None
    syncEnabled: bool

    model_config = {"from_attributes": True}


class SystemDefaultsResponse(BaseModel):
    """Constantes métier de `algorithms.py`, en lecture seule — aucune n'est
    configurable par organisation aujourd'hui (page Paramètres > Système)."""

    leakThresholdLph: float
    deliveryRiseThresholdMm: float
    deliveryStabilityDeltaMm: float
    deliveryStabilizationMinutes: float


# ================================================================
# CAISSE (page_caisse.md) — ventes estimées à partir des baisses de
# volume mesurées, jamais un état comptable officiel. Un triplet
# (valeur, devise, raison de non-calcul) reprend systématiquement le
# contrat déjà en place pour la valorisation du stock
# (`_resolve_tank_monetary_value`) : jamais un zéro silencieux.
# ================================================================


class CashSegmentResponse(BaseModel):
    """Un maillon de la traçabilité du calcul (page_caisse.md §20) : une
    fenêtre de temps sur une cuve, sa nature, et — si c'est une vente — son
    volume et sa valorisation."""

    startTime: datetime
    endTime: datetime
    type: str  # "sale" | "delivery" | "stable" | "anomaly_unexplained_rise" | "anomaly_extreme_variation" | "insufficient_data"
    startHeightMm: float | None
    endHeightMm: float | None
    startVolumeLiters: float | None
    endVolumeLiters: float | None
    volumeLiters: float
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None


class TankCashResponse(BaseModel):
    tankId: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    displayName: str
    fuelProductName: str
    periodStart: datetime
    periodEnd: datetime
    volumeSoldLiters: float | None
    volumeNotCalculableReason: str | None
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str  # "reliable" | "partial" | "incomplete_data" | "insufficient_data" | "anomaly"
    anomalyTypes: list[str]
    segments: list[CashSegmentResponse]


class TankCashSummaryLine(BaseModel):
    """Ligne cuve, sans les segments — utilisée dans le détail d'une
    station (page_caisse.md §19), la traçabilité complète n'étant chargée
    qu'au clic sur la cuve (endpoint dédié, jamais tout chargé d'un coup —
    page_caisse.md §31)."""

    tankId: uuid.UUID
    displayName: str
    fuelProductId: uuid.UUID
    fuelProductName: str
    volumeSoldLiters: float | None
    volumeNotCalculableReason: str | None
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str


class ProductCashLine(BaseModel):
    fuelProductId: uuid.UUID
    fuelProductName: str
    tankCount: int
    volumeSoldLiters: float
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str
    tanks: list[TankCashSummaryLine]


class StationCashDetailResponse(BaseModel):
    stationId: uuid.UUID
    stationName: str
    periodStart: datetime
    periodEnd: datetime
    tankCount: int
    volumeSoldLiters: float
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str
    products: list[ProductCashLine]


class StationCashSummaryLine(BaseModel):
    """Ligne station dans la vue réseau (page_caisse.md §17) — pas de détail
    produit/cuve ici, chargé seulement au clic (StationCashDetailResponse)."""

    stationId: uuid.UUID
    stationName: str
    tankCount: int
    volumeSoldLiters: float
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str


class CurrencyCashBlock(BaseModel):
    """Un bloc de caisse par devise réellement présente dans le réseau —
    jamais une somme entre devises différentes (page_caisse.md §H)."""

    currencyCode: str
    monetaryValue: float
    volumeSoldLiters: float
    stationCount: int
    stations: list[StationCashSummaryLine]


class NetworkCashSummaryResponse(BaseModel):
    periodStart: datetime
    periodEnd: datetime
    currencyBlocks: list[CurrencyCashBlock]
    volumeSoldLitersTotal: float
    stationsWithDataCount: int
    stationsTotalCount: int
    productCount: int
    incompletePricingStationCount: int
    lastMeasurementAt: datetime | None


# ================================================================
# Couche déclarative (processus-double-sources-verite, Phase 5-8) — un
# schéma Create/Response par type, jamais un schéma générique unique
# (cohérent avec Phase 5 §1 : chaque type reste sa propre entité).
# ================================================================


class CreateDeliveryDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    eventAt: datetime
    declaredVolumeLiters: float = Field(gt=0)
    # `supplierName` reste accepté (libellé libre, lignes hors référentiel) ;
    # quand `supplierId` est fourni et `supplierName` absent, le service le
    # fige au nom du fournisseur — snapshot documentaire, voir le modèle.
    supplierName: str | None = None
    supplierId: uuid.UUID | None = None
    truckId: uuid.UUID | None = None
    purchaseOrderId: uuid.UUID | None = None
    deliveryNoteReference: str | None = None
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None


class DeliveryDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    fuelProductId: uuid.UUID
    eventAt: datetime
    declaredAt: datetime
    declaredVolumeLiters: float
    supplierName: str | None
    supplierId: uuid.UUID | None
    truckId: uuid.UUID | None
    purchaseOrderId: uuid.UUID | None
    deliveryNoteReference: str | None
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


class CreateShiftCashDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    shiftStart: datetime
    shiftEnd: datetime
    declaredCashAmount: float = Field(ge=0)
    currencyId: uuid.UUID
    openingReadingMm: float | None = None
    closingReadingMm: float | None = None
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None


class ShiftCashDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    declaredAt: datetime
    shiftStart: datetime
    shiftEnd: datetime
    openingReadingMm: float | None
    closingReadingMm: float | None
    declaredCashAmount: float
    currencyId: uuid.UUID
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


class CreateManualGaugingDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    declaredHeightMm: float = Field(ge=0)
    method: str
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:
        if value not in ("dipstick", "gauge_pole", "other"):
            raise ValueError("method doit être 'dipstick', 'gauge_pole' ou 'other'.")
        return value


class ManualGaugingDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    declaredAt: datetime
    declaredHeightMm: float
    method: str
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


class CreateQualityCheckDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    waterDetected: bool
    method: str
    waterHeightMm: float | None = None
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:
        if value not in ("dipstick", "water_paste", "other"):
            raise ValueError("method doit être 'dipstick', 'water_paste' ou 'other'.")
        return value


class QualityCheckDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    declaredAt: datetime
    waterDetected: bool
    waterHeightMm: float | None
    method: str
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


class CreateLeakTestDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    result: str
    notes: str | None = None
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None

    @field_validator("result")
    @classmethod
    def _validate_result(cls, value: str) -> str:
        if value not in ("normal", "anomaly"):
            raise ValueError("result doit être 'normal' ou 'anomaly'.")
        return value


class LeakTestDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    tankId: uuid.UUID
    eventAt: datetime
    declaredAt: datetime
    result: str
    notes: str | None
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


class CreateIncidentDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    eventAt: datetime
    category: str
    description: str = Field(min_length=1)
    tankId: uuid.UUID | None = None
    changeReason: str | None = None
    correctsDeclarationId: uuid.UUID | None = None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        if value not in ("safety", "equipment", "quality", "security", "other"):
            raise ValueError("category doit être 'safety', 'equipment', 'quality', 'security' ou 'other'.")
        return value


class IncidentDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    tankId: uuid.UUID | None
    eventAt: datetime
    declaredAt: datetime
    category: str
    description: str
    lifecycleStatus: str
    changeReason: str | None
    correctsDeclarationId: uuid.UUID | None
    reconciledWithId: uuid.UUID | None
    reconciledWithType: str | None

    model_config = {"from_attributes": True}


# Modification en place, réservée à l'état 'declared' (Phase 5 §2/§3) — un
# seul schéma par type, jamais les champs d'identité (stationId, tankId,
# fuelProductId) : les changer reviendrait à changer la nature du fait
# déclaré, ce qui doit toujours passer par une nouvelle déclaration
# corrective (`correctsDeclarationId`), jamais une réécriture d'identité.
class UpdateDeliveryDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    declaredVolumeLiters: float | None = Field(default=None, gt=0)
    # Raccordements approvisionnement (facultatifs comme supplierName, jamais
    # des champs d'identité : null explicite = décrocher la ligne du
    # référentiel, champs absents = inchangé — sémantique exclude_unset).
    supplierName: str | None = None
    supplierId: uuid.UUID | None = None
    truckId: uuid.UUID | None = None
    purchaseOrderId: uuid.UUID | None = None
    deliveryNoteReference: str | None = None
    changeReason: str | None = None


class UpdateShiftCashDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    shiftStart: datetime | None = None
    shiftEnd: datetime | None = None
    openingReadingMm: float | None = None
    closingReadingMm: float | None = None
    declaredCashAmount: float | None = Field(default=None, ge=0)
    changeReason: str | None = None


class UpdateManualGaugingDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    declaredHeightMm: float | None = Field(default=None, ge=0)
    changeReason: str | None = None


class UpdateQualityCheckDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    waterDetected: bool | None = None
    waterHeightMm: float | None = None
    changeReason: str | None = None


class UpdateLeakTestDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    result: str | None = None
    notes: str | None = None
    changeReason: str | None = None

    @field_validator("result")
    @classmethod
    def _validate_result(cls, value: str | None) -> str | None:
        if value is not None and value not in ("normal", "anomaly"):
            raise ValueError("result doit être 'normal' ou 'anomaly'.")
        return value


class UpdateIncidentDeclarationRequest(BaseModel):
    eventAt: datetime | None = None
    description: str | None = None
    changeReason: str | None = None


# ================================================================
# Couche Commercial (processus-double-sources-verite, Phase 5 §5, Phase 7
# §2-3) — Bloc 3/4.
# ================================================================


class CreateCommercialAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    currencyId: uuid.UUID
    creditLimit: float = Field(ge=0)


class UpdateCommercialAccountRequest(BaseModel):
    name: str | None = None
    creditLimit: float | None = Field(default=None, ge=0)
    active: bool | None = None


class CommercialAccountResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    currencyId: uuid.UUID
    creditLimit: float
    active: bool

    model_config = {"from_attributes": True}


class CreateVehicleRequest(BaseModel):
    commercialAccountId: uuid.UUID
    plateOrReference: str = Field(min_length=1, max_length=50)


class VehicleResponse(BaseModel):
    id: uuid.UUID
    commercialAccountId: uuid.UUID
    plateOrReference: str

    model_config = {"from_attributes": True}


class CreateDriverRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    commercialAccountId: uuid.UUID | None = None


class DriverResponse(BaseModel):
    id: uuid.UUID
    commercialAccountId: uuid.UUID | None
    name: str

    model_config = {"from_attributes": True}


class CreateAuthorizationRequest(BaseModel):
    commercialAccountId: uuid.UUID
    vehicleId: uuid.UUID | None = None
    driverId: uuid.UUID | None = None
    reference: str | None = None


class AuthorizationResponse(BaseModel):
    id: uuid.UUID
    commercialAccountId: uuid.UUID
    vehicleId: uuid.UUID | None
    driverId: uuid.UUID | None
    reference: str | None
    active: bool

    model_config = {"from_attributes": True}


class CreateSaleRequest(BaseModel):
    stationId: uuid.UUID
    eventAt: datetime
    fuelProductId: uuid.UUID
    quantityLiters: float = Field(gt=0)
    priceAmount: float = Field(gt=0)
    currencyId: uuid.UUID
    paymentMethod: str
    commercialAccountId: uuid.UUID | None = None
    vehicleId: uuid.UUID | None = None
    driverId: uuid.UUID | None = None

    @field_validator("paymentMethod")
    @classmethod
    def _validate_payment_method(cls, value: str) -> str:
        # Élargi mission « vente-maintenant-reglementation » Bloc 3 — reflète
        # exactement la contrainte CHECK de app/modules/zylo_liquid/models.py.
        if value not in PAYMENT_METHODS:
            raise ValueError(f"paymentMethod doit être l'une des valeurs suivantes : {', '.join(PAYMENT_METHODS)}.")
        return value


class SaleResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    eventAt: datetime
    fuelProductId: uuid.UUID
    quantityLiters: float
    priceAmount: float
    currencyId: uuid.UUID
    paymentMethod: str
    commercialAccountId: uuid.UUID | None
    vehicleId: uuid.UUID | None
    driverId: uuid.UUID | None

    model_config = {"from_attributes": True}


class ReceivableResponse(BaseModel):
    id: uuid.UUID
    commercialAccountId: uuid.UUID
    # Exactement l'un des deux renseigné (contrainte DB ck_zlReceivable_exactly_one_origin,
    # extension mission « vente-maintenant-reglementation » Bloc 4 corrigé).
    saleId: uuid.UUID | None
    productSaleTransactionId: uuid.UUID | None
    amount: float
    currencyId: uuid.UUID
    status: str

    model_config = {"from_attributes": True}


class CreatePaymentRequest(BaseModel):
    receivableId: uuid.UUID
    paidAt: datetime
    amount: float = Field(gt=0)
    currencyId: uuid.UUID
    # Obligatoire si currencyId diffère de la devise de la créance (Phase 5
    # §5.1 de 05-modele-declaratif.md) : snapshot capturé au paiement,
    # jamais une référence vivante vers un taux qui pourrait changer après coup.
    exchangeRateApplied: float | None = Field(default=None, gt=0)
    method: str | None = None


class PaymentResponse(BaseModel):
    id: uuid.UUID
    receivableId: uuid.UUID
    authorUserId: uuid.UUID
    paidAt: datetime
    amount: float
    currencyId: uuid.UUID
    exchangeRateApplied: float | None
    method: str | None

    model_config = {"from_attributes": True}


# ================================================================
# Modèle documentaire (Phase 5 §6) — Bloc 5.
# ================================================================


class CreateDocumentRequest(BaseModel):
    storageReference: str = Field(min_length=1, max_length=500)
    fileName: str = Field(min_length=1, max_length=255)
    mimeType: str | None = None
    # Lien initial optionnel — un document peut aussi être créé sans lien et
    # rattaché ensuite via POST /document-links (association logique, Phase
    # 5 §6 : plusieurs entités peuvent référencer le même Document).
    linkedEntityType: str | None = None
    linkedEntityId: uuid.UUID | None = None
    # Mission « vente-maintenant-reglementation », Phase 5 §4 — 'normal' par
    # défaut, 'restreint' nécessite DOCUMENT_READ_SENSITIVE pour être relu.
    sensitivityLevel: str = "normal"
    supersedesDocumentId: uuid.UUID | None = None

    @field_validator("sensitivityLevel")
    @classmethod
    def _validate_sensitivity_level(cls, value: str) -> str:
        if value not in ("normal", "restreint"):
            raise ValueError("sensitivityLevel doit être 'normal' ou 'restreint'.")
        return value


class DocumentResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    storageReference: str
    fileName: str
    mimeType: str | None
    uploadedByUserId: uuid.UUID
    sensitivityLevel: str
    supersedesDocumentId: uuid.UUID | None
    deletedAt: datetime | None

    model_config = {"from_attributes": True}


class CreateDocumentLinkRequest(BaseModel):
    documentId: uuid.UUID
    linkedEntityType: str = Field(min_length=1, max_length=40)
    linkedEntityId: uuid.UUID


class DocumentLinkResponse(BaseModel):
    id: uuid.UUID
    documentId: uuid.UUID
    linkedEntityType: str
    linkedEntityId: uuid.UUID

    model_config = {"from_attributes": True}


class DocumentDownloadUrlResponse(BaseModel):
    url: str


class DocumentCountsResponse(BaseModel):
    """Nombre de pièces jointes par entité (audit performance — remplace
    un appel par ligne de tableau). Une entité absente des clés n'a
    simplement aucun document, jamais une erreur."""

    counts: dict[uuid.UUID, int]


# ================================================================
# Rapprochement (Phase 6, Phase 7 §1) — Bloc 6 : modèles/schémas seulement,
# le mécanisme de calcul est le Bloc 7.
# ================================================================


class UpsertStationReconciliationSettingsRequest(BaseModel):
    """Un seul schéma pour créer ou remplacer la dérogation d'une station —
    chaque champ NULL/absent signifie repli sur le défaut réseau (Phase 7 §1)."""

    deliveryWindowHours: float | None = Field(default=None, gt=0)
    deliveryVolumeToleranceFixedLiters: float | None = Field(default=None, ge=0)
    deliveryVolumeTolerancePercent: float | None = Field(default=None, ge=0)
    gaugingHeightToleranceMm: float | None = Field(default=None, ge=0)
    qualityCheckWindowHours: float | None = Field(default=None, gt=0)


class StationReconciliationSettingsResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    deliveryWindowHours: float | None
    deliveryVolumeToleranceFixedLiters: float | None
    deliveryVolumeTolerancePercent: float | None
    gaugingHeightToleranceMm: float | None
    qualityCheckWindowHours: float | None

    model_config = {"from_attributes": True}


class ReconciliationRecordResponse(BaseModel):
    id: uuid.UUID
    subjectType: str
    subjectId: uuid.UUID
    counterpartType: str | None
    counterpartId: str | None
    family: str
    status: str
    discrepancyValue: float | None
    discrepancyUnit: str | None
    toleranceApplied: float | None
    evaluatedAt: datetime
    evaluatedByUserId: uuid.UUID | None

    model_config = {"from_attributes": True}


# ================================================================
# Couche Approvisionnement — fusion de la page prototype #/livraisons avec
# la couche réelle (décision commanditaire « créer toutes les tables
# nécessaires, même fournisseur »). Fournisseur/transporteur/camion :
# référentiels réseau portée organisation entière, mêmes conventions que
# CommercialAccount. Commande : portée station (comme une déclaration),
# pas de schéma de mise à jour — son cycle de vie (open → received) est
# piloté par les réceptions, jamais éditée en place.
# ================================================================


SUPPLIER_CATEGORIES = ("carburant", "equipement", "maintenance", "securite", "service", "autre")


def _validate_supplier_category(value: str | None) -> str | None:
    if value is not None and value not in SUPPLIER_CATEGORIES:
        raise ValueError(f"category doit être l'une de {SUPPLIER_CATEGORIES}.")
    return value


class CreateSupplierRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: str | None = Field(default=None, max_length=60)
    category: str | None = None
    contactName: str | None = Field(default=None, max_length=150)
    contactRole: str | None = Field(default=None, max_length=100)
    contactPhone: str | None = Field(default=None, max_length=30)
    contactEmail: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    address: str | None = None

    _validate_category = field_validator("category")(_validate_supplier_category)


class UpdateSupplierRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: str | None = Field(default=None, max_length=60)
    category: str | None = None
    contactName: str | None = Field(default=None, max_length=150)
    contactRole: str | None = Field(default=None, max_length=100)
    contactPhone: str | None = Field(default=None, max_length=30)
    contactEmail: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    address: str | None = None
    active: bool | None = None

    _validate_category = field_validator("category")(_validate_supplier_category)


class SupplierResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    type: str | None
    category: str | None = None
    contactName: str | None = None
    contactRole: str | None = None
    contactPhone: str | None = None
    contactEmail: str | None = None
    website: str | None = None
    address: str | None = None
    active: bool

    model_config = {"from_attributes": True}


class CreateCarrierRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class UpdateCarrierRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    active: bool | None = None


class CarrierResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    active: bool

    model_config = {"from_attributes": True}


class CreateTruckRequest(BaseModel):
    carrierId: uuid.UUID | None = None
    plateNumber: str = Field(min_length=1, max_length=50)
    capacityLiters: float | None = Field(default=None, gt=0)
    compartmentsCount: int | None = Field(default=None, gt=0, le=20)


class UpdateTruckRequest(BaseModel):
    carrierId: uuid.UUID | None = None
    plateNumber: str | None = Field(default=None, min_length=1, max_length=50)
    capacityLiters: float | None = Field(default=None, gt=0)
    compartmentsCount: int | None = Field(default=None, gt=0, le=20)


class TruckResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    carrierId: uuid.UUID | None
    plateNumber: str
    capacityLiters: float | None
    compartmentsCount: int | None

    model_config = {"from_attributes": True}


class CreatePurchaseOrderRequest(BaseModel):
    stationId: uuid.UUID
    tankId: uuid.UUID
    supplierId: uuid.UUID
    orderReference: str = Field(min_length=1, max_length=100)
    orderedVolumeLiters: float = Field(gt=0)
    expectedAt: datetime | None = None


class PurchaseOrderResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    tankId: uuid.UUID
    supplierId: uuid.UUID
    authorUserId: uuid.UUID
    orderReference: str
    orderedVolumeLiters: float
    orderedAt: datetime
    expectedAt: datetime | None
    status: str

    model_config = {"from_attributes": True}


# ================================================================
# Centre administratif et opérationnel de la station — domaines Sécurité
# (SecurityEquipment), Fournisseurs par station (StationSupplier) et
# Finances (sous-ressource dédiée sur Station, jamais dans StationResponse
# standard — voir plus bas).
# ================================================================


_SECURITY_EQUIPMENT_CATEGORIES = ("extincteur", "systeme_incendie", "arret_urgence", "point_evacuation", "zone_atex", "autre")
_SECURITY_EQUIPMENT_CONFORMITY_STATUSES = ("conforme", "non_conforme", "a_controler")


def _validate_security_equipment_category(value: str | None) -> str | None:
    if value is not None and value not in _SECURITY_EQUIPMENT_CATEGORIES:
        raise ValueError(f"category doit être l'un de {_SECURITY_EQUIPMENT_CATEGORIES}.")
    return value


def _validate_security_equipment_conformity_status(value: str | None) -> str | None:
    if value is not None and value not in _SECURITY_EQUIPMENT_CONFORMITY_STATUSES:
        raise ValueError(f"conformityStatus doit être l'un de {_SECURITY_EQUIPMENT_CONFORMITY_STATUSES}.")
    return value


class CreateSecurityEquipmentRequest(BaseModel):
    stationId: uuid.UUID
    category: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=150)
    lastControlAt: date | None = None
    nextControlDueAt: date | None = None
    conformityStatus: str = "a_controler"
    notes: str | None = None

    _validate_category = field_validator("category")(_validate_security_equipment_category)
    _validate_conformity_status = field_validator("conformityStatus")(_validate_security_equipment_conformity_status)


class UpdateSecurityEquipmentRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=30)
    label: str | None = Field(default=None, min_length=1, max_length=150)
    lastControlAt: date | None = None
    nextControlDueAt: date | None = None
    conformityStatus: str | None = None
    notes: str | None = None

    _validate_category = field_validator("category")(_validate_security_equipment_category)
    _validate_conformity_status = field_validator("conformityStatus")(_validate_security_equipment_conformity_status)


class SecurityEquipmentResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    category: str
    label: str
    lastControlAt: date | None
    nextControlDueAt: date | None
    conformityStatus: str
    notes: str | None

    model_config = {"from_attributes": True}


class CreateStationSupplierRequest(BaseModel):
    stationId: uuid.UUID
    supplierId: uuid.UUID
    notes: str | None = None
    contractReference: str | None = Field(default=None, max_length=100)
    contractType: str | None = Field(default=None, max_length=60)
    contractStartDate: date | None = None
    contractEndDate: date | None = None
    equipmentTags: str | None = None


class UpdateStationSupplierRequest(BaseModel):
    active: bool | None = None
    notes: str | None = None
    contractReference: str | None = Field(default=None, max_length=100)
    contractType: str | None = Field(default=None, max_length=60)
    contractStartDate: date | None = None
    contractEndDate: date | None = None
    equipmentTags: str | None = None


class StationSupplierResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    supplierId: uuid.UUID
    active: bool
    notes: str | None
    contractReference: str | None = None
    contractType: str | None = None
    contractStartDate: date | None = None
    contractEndDate: date | None = None
    equipmentTags: str | None = None
    # Calculé côté service depuis contractEndDate (jamais saisi), même
    # sémantique que `RegulatoryDocumentResponse.computedStatus` : 'valid' /
    # 'renew_soon' / 'expired' / 'unknown' (pas de date de fin connue).
    contractStatus: str = "unknown"

    model_config = {"from_attributes": True}


class UpdateStationFinancialRequest(BaseModel):
    taxId: str | None = None
    billingAddress: str | None = None
    costCenterCode: str | None = None
    bankAccountInfo: str | None = None


class StationFinancialResponse(BaseModel):
    """Sous-ressource dédiée, jamais fusionnée dans StationResponse — gardée
    intégralement derrière STATION_FINANCIAL_READ (y compris taxId/
    billingAddress/costCenterCode, pas seulement bankAccountInfo : une
    seule frontière de permission pour tout le domaine Finances, plus
    simple à garantir qu'un mélange de champs publics/sensibles sur le
    même schéma)."""

    stationId: uuid.UUID
    taxId: str | None
    billingAddress: str | None
    costCenterCode: str | None
    bankAccountInfo: str | None

    model_config = {"from_attributes": True}


# ================================================================
# Module Personnel — création de compte + profil de poste pour un membre du
# personnel d'une station (mockup emalioration/personnel/). Le rôle
# lui-même reste géré par le RBAC existant (assign_role), jamais dupliqué.
# ================================================================


class CreateStationStaffRequest(BaseModel):
    stationId: uuid.UUID
    firstName: str = Field(min_length=1, max_length=120)
    lastName: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    photoStorageReference: str | None = None
    roleId: uuid.UUID | None = None
    employeeNumber: str | None = Field(default=None, max_length=50)
    contractType: str | None = Field(default=None, max_length=50)
    directManagerUserId: uuid.UUID | None = None


class UpdateStationStaffRequest(BaseModel):
    firstName: str | None = Field(default=None, min_length=1, max_length=120)
    lastName: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    photoStorageReference: str | None = None
    employeeNumber: str | None = Field(default=None, max_length=50)
    contractType: str | None = Field(default=None, max_length=50)
    assignedStationId: uuid.UUID | None = None
    directManagerUserId: uuid.UUID | None = None


class StationStaffResponse(BaseModel):
    id: uuid.UUID
    userId: uuid.UUID
    organizationId: uuid.UUID
    email: str
    fullName: str
    firstName: str | None
    lastName: str | None
    phone: str | None
    photoUrl: str | None
    status: str
    employeeNumber: str | None
    contractType: str | None
    assignedStationId: uuid.UUID | None
    directManagerUserId: uuid.UUID | None
    assignedAt: date

    model_config = {"from_attributes": True}


class CreateStationStaffResponse(BaseModel):
    """Le mot de passe temporaire n'apparaît QUE dans cette réponse, une
    seule fois, à la création — jamais stocké en clair, jamais rejoué par
    aucun autre endpoint (StationStaffResponse ne le porte pas)."""

    staff: StationStaffResponse
    temporaryPassword: str


# ================================================================
# Page Exploitation (Centre administratif de la station) — catalogue de
# services et politique commerciale par produit. Les seuils/l'overview des
# carburants sont définis plus haut, avec StationFuelProductResponse.
# ================================================================


class CreateStationServiceRequest(BaseModel):
    stationId: uuid.UUID
    type: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=150)
    available: bool = True


class UpdateStationServiceRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=150)
    available: bool | None = None


class StationServiceResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    type: str
    label: str
    available: bool

    model_config = {"from_attributes": True}


class UpdatePricingPolicyRequest(BaseModel):
    policyType: str | None = Field(default=None, max_length=30)
    applicationPeriod: str | None = Field(default=None, max_length=30)
    promotionsEnabled: bool | None = None
    differentPriceByPeriod: bool | None = None
    volumeDiscount: bool | None = None
    corporateRate: bool | None = None


class PricingPolicyResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    policyType: str
    applicationPeriod: str
    promotionsEnabled: bool
    differentPriceByPeriod: bool
    volumeDiscount: bool
    corporateRate: bool

    model_config = {"from_attributes": True}


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 5 : catalogue de
# produits vendables (boutique/non-carburant).
# ================================================================


class CreateSellableProductRequest(BaseModel):
    stationId: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=60)
    barcodeValue: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=60)
    unitPriceAmount: float = Field(gt=0)
    currencyId: uuid.UUID


class UpdateSellableProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=60)
    barcodeValue: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=60)
    unitPriceAmount: float | None = Field(default=None, gt=0)
    active: bool | None = None


class SellableProductResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    stationId: uuid.UUID | None
    name: str
    sku: str | None
    barcodeValue: str | None
    category: str | None
    unitPriceAmount: float
    currencyId: uuid.UUID
    active: bool

    model_config = {"from_attributes": True}


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 4 (corrigé) : ventes de
# produits boutique. Entité séparée de Sale (cf. models.py, docstring
# ProductSaleTransaction).
# ================================================================


class ProductSaleLineRequest(BaseModel):
    sellableProductId: uuid.UUID
    quantity: float = Field(gt=0)
    unitPriceAmount: float = Field(gt=0)


class CreateProductSaleTransactionRequest(BaseModel):
    stationId: uuid.UUID
    eventAt: datetime
    currencyId: uuid.UUID
    paymentMethod: str
    lines: list[ProductSaleLineRequest] = Field(min_length=1)
    commercialAccountId: uuid.UUID | None = None

    @field_validator("paymentMethod")
    @classmethod
    def _validate_payment_method(cls, value: str) -> str:
        if value not in PAYMENT_METHODS:
            raise ValueError(f"paymentMethod doit être l'une des valeurs suivantes : {', '.join(PAYMENT_METHODS)}.")
        return value


class ProductSaleLineResponse(BaseModel):
    id: uuid.UUID
    transactionId: uuid.UUID
    sellableProductId: uuid.UUID
    quantity: float
    unitPriceAmount: float
    lineTotalAmount: float

    model_config = {"from_attributes": True}


class ProductSaleTransactionResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    authorUserId: uuid.UUID
    eventAt: datetime
    currencyId: uuid.UUID
    paymentMethod: str
    totalAmount: float
    status: str
    commercialAccountId: uuid.UUID | None
    cancelledAt: datetime | None
    cancelledByUserId: uuid.UUID | None
    lines: list[ProductSaleLineResponse] = []

    model_config = {"from_attributes": True}


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 6 : Maintenance.
# ================================================================


class CreateTechnicianRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    linkedUserId: uuid.UUID | None = None


class TechnicianResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    company: str | None
    contact: str | None
    linkedUserId: uuid.UUID | None
    active: bool

    model_config = {"from_attributes": True}


class CreateEquipmentRequest(BaseModel):
    stationId: uuid.UUID
    type: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serialNumber: str | None = Field(default=None, max_length=200)
    installedAt: date | None = None
    warrantyUntil: date | None = None


class UpdateEquipmentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    manufacturer: str | None = None
    model: str | None = None
    serialNumber: str | None = None
    status: str | None = None
    warrantyUntil: date | None = None
    lastMaintenanceAt: date | None = None
    nextMaintenanceDueAt: date | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ("in_service", "out_of_order", "out_of_service"):
            raise ValueError("status doit être 'in_service', 'out_of_order' ou 'out_of_service'.")
        return value


class EquipmentResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    type: str
    name: str
    manufacturer: str | None
    model: str | None
    serialNumber: str | None
    status: str
    installedAt: date | None
    warrantyUntil: date | None
    lastMaintenanceAt: date | None
    nextMaintenanceDueAt: date | None

    model_config = {"from_attributes": True}


class CreateInterventionRequest(BaseModel):
    equipmentId: uuid.UUID
    stationId: uuid.UUID
    priority: str
    type: str
    description: str = Field(min_length=1)
    plannedAt: datetime | None = None
    linkedAlertId: uuid.UUID | None = None

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, value: str) -> str:
        if value not in ("critical", "high", "medium", "low"):
            raise ValueError("priority doit être 'critical', 'high', 'medium' ou 'low'.")
        return value

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in ("preventive", "corrective"):
            raise ValueError("type doit être 'preventive' ou 'corrective'.")
        return value


class AssignInterventionRequest(BaseModel):
    technicianId: uuid.UUID


class CloseInterventionRequest(BaseModel):
    diagnosis: str | None = None
    actionTaken: str | None = None
    cost: float | None = Field(default=None, ge=0)


class InterventionResponse(BaseModel):
    id: uuid.UUID
    equipmentId: uuid.UUID
    stationId: uuid.UUID
    priority: str
    type: str
    description: str
    technicianId: uuid.UUID | None
    status: str
    openedAt: datetime
    plannedAt: datetime | None
    closedAt: datetime | None
    cost: float | None
    diagnosis: str | None
    actionTaken: str | None
    linkedAlertId: uuid.UUID | None

    model_config = {"from_attributes": True}


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 7 : Réglementation.
# ================================================================


class CreateRegulatoryDocumentRequest(BaseModel):
    stationId: uuid.UUID
    documentType: str = Field(min_length=1, max_length=80)
    authority: str | None = Field(default=None, max_length=200)
    issuedAt: date | None = None
    expiresAt: date | None = None
    sourceReference: str | None = None
    certaintyLevel: str = "medium"
    notes: str | None = None
    responsibleUserId: uuid.UUID | None = None

    @field_validator("certaintyLevel")
    @classmethod
    def _validate_certainty_level(cls, value: str) -> str:
        if value not in ("high", "medium", "low"):
            raise ValueError("certaintyLevel doit être 'high', 'medium' ou 'low'.")
        return value


class UpdateRegulatoryDocumentRequest(BaseModel):
    """Correction de métadonnées uniquement (refonte onglet Réglementation) —
    jamais `documentType`/`issuedAt`/`expiresAt`/`certaintyLevel`, qui
    restent gouvernés par `renew_regulatory_document` (un vrai changement
    de date est un renouvellement, jamais une correction silencieuse)."""
    authority: str | None = Field(default=None, max_length=200)
    sourceReference: str | None = None
    notes: str | None = None
    responsibleUserId: uuid.UUID | None = None


class RegulatoryDocumentResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    documentType: str
    authority: str | None
    issuedAt: date | None
    expiresAt: date | None
    sourceReference: str | None
    certaintyLevel: str
    supersededByDocumentId: uuid.UUID | None
    notes: str | None = None
    responsibleUserId: uuid.UUID | None = None
    # Résolus côté service depuis `responsibleUserId` (jamais stockés en
    # double) — `None` tant qu'aucun responsable n'est désigné.
    responsibleUserName: str | None = None
    responsibleUserEmail: str | None = None
    # Calculé côté service (jamais un attribut du modèle ORM, jamais saisi —
    # Phase 4 §3.1 de la mission), assigné après `model_validate` : valeur
    # par défaut ici uniquement pour permettre cette validation en 2 temps.
    # 'valid' / 'renew_soon' / 'expired' / 'unknown' (pas d'échéance connue).
    computedStatus: str = "unknown"

    model_config = {"from_attributes": True}


class CreateRegulatoryDeclarationRequest(BaseModel):
    stationId: uuid.UUID
    type: str = Field(min_length=1, max_length=80)
    authority: str | None = Field(default=None, max_length=200)
    triggerIncidentId: uuid.UUID | None = None
    reserve: str | None = None


class RegulatoryDeclarationResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    type: str
    authority: str | None
    triggerIncidentId: uuid.UUID | None
    status: str
    reserve: str | None

    model_config = {"from_attributes": True}
