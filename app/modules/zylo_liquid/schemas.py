import colorsys
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_serializer, field_validator

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
    closedWeekdays: str | None = Field(default=None, description="Jours de fermeture hebdomadaire, CSV de jours ISO (1=lundi..7=dimanche), ex. \"7\" ou \"6,7\". `None`/vide = ouvert tous les jours.")
    notes: str | None = None
    currencyOverrideId: uuid.UUID | None = Field(default=None, description="Devise spécifique à cette station si différente de la devise par défaut de l'organisation.")
    # Champs commerce/amenities — présents sur le modèle Station depuis le
    # début (phase-1-database.md §5) mais jamais exposés par aucun schéma
    # jusqu'ici (Centre administratif et opérationnel de la station, domaines
    # Exploitation/Infrastructure).
    exploitationType: str = Field(default="propre", max_length=20, description="Mode d'exploitation de la station (ex. \"propre\" pour une station en gestion directe, vs. gérance/franchise) — pas de contrainte enum en base, valeur libre.")
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
    status: str = Field(description="\"active\" ou \"inactive\" — basculé par les endpoints `/deactivate` et `/reactivate`, jamais modifié via un PATCH direct.")
    integrationDate: date | None = Field(description="Date d'entrée de la station dans le réseau/l'organisation (pas la date de création de l'enregistrement).")
    notes: str | None
    activeTankCount: int = Field(default=0, description="Nombre de cuves actives rattachées à la station, calculé à la volée — jamais stocké en base.")
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
    heightAlarmMm: float = Field(gt=0, description="Seuil haut critique (mm) : hauteur de produit au-delà de laquelle une alarme de débordement se déclenche.")
    heightAlertMm: float = Field(gt=0, description="Seuil haut d'alerte (mm), plus bas que `heightAlarmMm` — signale un remplissage important sans être encore critique.")
    lowAlarmMm: float = Field(gt=0, description="Seuil bas critique (mm) : hauteur de produit en-dessous de laquelle la cuve est considérée en stock bas (déclenche l'indicateur visuel réservé, cf. `_reject_reserved_red`).")
    alertWaterMaxMm: float = Field(default=25.00, description="Hauteur d'eau maximale tolérée au fond de la cuve (mm) avant déclenchement d'une alerte eau — l'eau se dépose sous le carburant et fausse le jaugeage si elle s'accumule.")
    dataSourceType: str = Field(default="console", description="Origine des mesures de niveau pour cette cuve (ex. \"console\" pour une jauge manuelle, capteur télémétrique sinon) — détermine si un mapping capteur Holykell est attendu.")


class UpdateTankRequest(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=100)
    capacityLiters: float | None = Field(default=None, gt=0)
    calibratedCapacityLiters: float | None = Field(default=None, description="Capacité réelle mesurée par jaugeage (peut différer de `capacityLiters`, la capacité nominale constructeur) — utilisée pour les calculs de volume quand disponible.")
    tankHeightMm: float | None = Field(default=None, gt=0)
    fuelProductId: uuid.UUID | None = Field(default=None, description="Nouveau produit carburant existant à associer à la cuve — exclusif avec newFuelProductName/newFuelProductCode (P0-1, audit module Stations 2026-09-16).")
    newFuelProductName: str | None = Field(default=None, min_length=1, max_length=100, description="Crée un nouveau produit carburant à la volée puis l'associe à la cuve — exclusif avec fuelProductId, requiert newFuelProductCode.")
    newFuelProductCode: str | None = Field(default=None, min_length=1, max_length=10)
    heightAlarmMm: float | None = Field(default=None, description="Seuil haut critique (mm), voir `CreateTankRequest.heightAlarmMm`.")
    heightAlertMm: float | None = Field(default=None, description="Seuil haut d'alerte (mm), voir `CreateTankRequest.heightAlertMm`.")
    lowAlarmMm: float | None = Field(default=None, description="Seuil bas critique (mm), voir `CreateTankRequest.lowAlarmMm`.")
    alertWaterMaxMm: float | None = Field(default=None, description="Hauteur d'eau maximale tolérée (mm), voir `CreateTankRequest.alertWaterMaxMm`.")
    active: bool | None = None
    notes: str | None = None


class TankResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    fuelProductId: uuid.UUID
    tankNumber: int
    displayName: str
    capacityLiters: float
    calibratedCapacityLiters: float | None = Field(description="Capacité réelle mesurée par jaugeage, si elle a été établie — sinon `None` et `capacityLiters` (capacité nominale) fait foi.")
    tankHeightMm: float | None
    dataSourceType: str
    heightAlarmMm: float
    heightAlertMm: float
    lowAlarmMm: float
    alertWaterMaxMm: float
    active: bool
    productSince: date | None = Field(description="Date depuis laquelle la cuve contient son produit actuel (pertinent après un changement de produit).")
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
    sensorStatus: str = Field(description="\"online\" (mesures récentes reçues), \"offline\" (capteur mappé mais silencieux) ou \"not_configured\" (aucun capteur mappé à cette cuve).")
    heightMm: float | None
    volumeLiters: float | None = Field(description="Volume brut déduit de la hauteur via la table de jaugeage. `None` si non calculable — voir `volumeNotCalculableReason`.")
    volumeNotCalculableReason: str | None = Field(description="Explique pourquoi `volumeLiters` est `None` (ex. pas de mesure récente, table de jaugeage absente) — jamais de volume inventé par défaut.")
    volumeLiters15C: float | None = Field(description="Volume corrigé à 15°C (référence standard carburant) via le coefficient de dilatation thermique du produit, quand la température est disponible.")
    sellableVolumeLiters: float | None = Field(description="Volume net moins le seuil bas (`lowAlarmMm`) de la cuve : le volume réellement vendable, jamais rien sous ce seuil.")
    waterHeightMm: float | None
    waterVolumeLiters: float | None
    temperatureC: float | None
    emptyVolumeLiters: float | None = Field(description="Volume restant disponible avant d'atteindre la capacité (calibrée ou nominale) de la cuve — utile pour dimensionner une prochaine livraison.")
    lastMeasurementAt: datetime | None
    monetaryValue: float | None = Field(default=None, description="Valeur monétaire du stock courant (volume × prix unitaire courant). `None` si non calculable — voir `monetaryValueNotCalculableReason`.")
    currencyCode: str | None = None
    monetaryValueNotCalculableReason: str | None = None
    unitPriceAmount: float | None = None


class StationCurrentStateResponse(BaseModel):
    stationId: uuid.UUID
    tanks: list[TankCurrentStateResponse]


class TankMeasurementResponse(BaseModel):
    id: int
    measuredAt: datetime
    rawValue: float = Field(description="Valeur brute remontée par le capteur, dans l'unité indiquée par `unit` (pas forcément un volume — peut être une hauteur selon le type de mesure).")
    unit: str | None
    volumeLiters: float | None = Field(description="Volume dérivé de `rawValue` via la table de jaugeage, si applicable et calculable au moment de la mesure.")
    isCorrection: bool = Field(description="True si ce point est une correction manuelle a posteriori plutôt qu'une mesure brute du capteur (ex. recalage après vérification physique).")

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
    # Volume vendable (audit "cartes stock", validé) : volume net moins le
    # seuil bas de chaque cuve (jamais rien de vendable sous ce seuil) —
    # toujours calculable dès que `totalVolumeLiters` l'est (même table de
    # calibration), donc jamais de raison de non-calcul séparée. Sa valeur
    # monétaire réutilise exactement le même prix/devise/raison que
    # `totalMonetaryValue` (même résolution de prix par cuve) — jamais une
    # deuxième résolution de prix.
    totalSellableVolumeLiters: float = 0.0
    totalSellableMonetaryValue: float | None = None


class NetworkSummaryResponse(BaseModel):
    products: list[NetworkSummaryProductLine]
    totalVolumeLiters: float
    totalStationCount: int
    totalTankCount: int
    # Somme pure, toujours calculable (comme `totalVolumeLiters`) — la
    # valeur monétaire totale vendable, elle, reste calculée côté frontend
    # à partir des lignes produit (`useNetworkDashboard.ts`), exactement
    # comme `totalMonetaryValue` l'est déjà aujourd'hui pour le stock total.
    totalSellableVolumeLiters: float = 0.0


class DeliveryDetectedResponse(BaseModel):
    id: uuid.UUID
    tankId: uuid.UUID
    stationId: uuid.UUID
    startTime: datetime = Field(description="Début de la montée de niveau détectée par l'algorithme de surveillance (pas l'heure d'arrivée du camion, qui n'est pas connue ici).")
    startHeightMm: float
    endTime: datetime = Field(description="Moment où le niveau s'est stabilisé (`DELIVERY_STABILIZATION_MINUTES` sans variation significative), marquant la livraison comme terminée.")
    endHeightMm: float
    volumeLiters: float | None = Field(description="Volume livré, déduit de la différence de hauteur via la table de jaugeage. `None` si non calculable (ex. table de jaugeage absente sur la période).")

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


# ResolveAlertRequest / AlertResponse — déplacés vers `app/alerts/schemas.py`
# (2026-09-15, Phase 3 de la migration monolithe modulaire).


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

    @field_serializer("effectiveFrom")
    def _serialize_effective_from(self, value: datetime) -> str:
        # `effectiveFrom` est stocké naïf-UTC (convention du module, voir
        # `_to_naive_utc`) — sans marqueur de fuseau explicite, `new Date()`
        # côté frontend le réinterprète comme heure LOCALE au lieu d'UTC,
        # provoquant un horodatage décalé de l'offset du fuseau de
        # l'utilisateur (P0-6, audit module Stations 2026-09-16). On force
        # ici le suffixe UTC explicite sur ce champ précis, sans toucher au
        # type de colonne ni aux autres champs naïfs du module.
        return value.replace(tzinfo=timezone.utc).isoformat()


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


class NetworkProductCashLine(BaseModel):
    """Ventes du jour agrégées par produit sur tout le réseau (cartes de la
    page Caisse, même esprit que NetworkSummaryProductLine pour le stock) —
    le volume s'additionne toujours, le montant seulement si toutes les
    stations contributrices partagent la même devise (même garde que
    CurrencyCashBlock, jamais une somme entre devises différentes)."""

    fuelProductId: uuid.UUID
    fuelProductName: str
    displayColor: str | None
    tankCount: int
    stationCount: int
    volumeSoldLiters: float
    monetaryValue: float | None
    currencyCode: str | None
    monetaryValueNotCalculableReason: str | None
    confidence: str
    stations: list[StationCashSummaryLine]


class NetworkCashSummaryResponse(BaseModel):
    periodStart: datetime
    periodEnd: datetime
    currencyBlocks: list[CurrencyCashBlock]
    productBlocks: list[NetworkProductCashLine]
    # Toutes les stations actives ayant au moins une cuve, y compris celles
    # dont le montant n'est pas calculable (raison explicite) — contrairement
    # à `currencyBlocks[].stations`, qui n'inclut que les stations dont la
    # devise a pu être résolue. Nécessaire pour un tableau/filtrage par
    # station qui ne doit jamais faire disparaître silencieusement une
    # station en délai de prix.
    stationLines: list[StationCashSummaryLine]
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


# Modèle documentaire — déplacé vers `app/files/schemas.py` (2026-09-15,
# Phase 1 de la migration monolithe modulaire). Import direct depuis ce
# module public pour l'unique appelant restant ici
# (`generate_purchase_order_document`), jamais une redéfinition locale.


# ================================================================
# Rapprochement (Phase 6, Phase 7 §1) — Bloc 6 : modèles/schémas seulement,
# le mécanisme de calcul est le Bloc 7.
# ================================================================


class UpsertStationReconciliationSettingsRequest(BaseModel):
    """Un seul schéma pour créer ou remplacer la dérogation d'une station —
    chaque champ NULL/absent signifie repli sur le défaut réseau (Phase 7 §1)."""

    deliveryWindowHours: float | None = Field(default=None, gt=0, description="Fenêtre de temps (heures) autour d'une livraison déclarée dans laquelle on cherche une livraison détectée correspondante.")
    deliveryVolumeToleranceFixedLiters: float | None = Field(default=None, ge=0, description="Écart de volume (litres) toléré entre déclaré et détecté avant de considérer une livraison en discordance — tolérance fixe, cumulable avec la tolérance en pourcentage.")
    deliveryVolumeTolerancePercent: float | None = Field(default=None, ge=0, description="Écart de volume toléré, exprimé en pourcentage du volume détecté.")
    gaugingHeightToleranceMm: float | None = Field(default=None, ge=0, description="Écart de hauteur (mm) toléré entre un jaugeage manuel déclaré et la hauteur mesurée par le capteur au même instant.")
    qualityCheckWindowHours: float | None = Field(default=None, gt=0, description="Fenêtre de temps (heures) dans laquelle un contrôle qualité déclaré doit se rattacher à une livraison pour être réconcilié avec elle.")


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
    subjectType: str = Field(description="Type de l'entité côté « déclaré » comparée (ex. \"TankStockDay\" pour un rapprochement de stock journalier) — avec `subjectId`, identifie la donnée source de la comparaison.")
    subjectId: uuid.UUID
    counterpartType: str | None = Field(description="Type de l'entité côté « mesuré/détecté » comparée (ex. l'agrégat télémétrique). `None` si le rapprochement n'a pas de contrepartie distincte.")
    counterpartId: str | None
    family: str = Field(description="Catégorie de rapprochement (ex. \"quantitative\") — regroupe les différents types de vérifications (stock, livraison, jaugeage...) par nature de comparaison.")
    status: str = Field(description="\"matched\" si l'écart est dans la tolérance, \"discrepancy\" au-delà, \"insufficient_data\" si la contrepartie mesurée n'est pas disponible pour calculer un écart.")
    discrepancyValue: float | None = Field(description="Écart absolu constaté entre déclaré et mesuré, dans l'unité `discrepancyUnit`. `None` si `status` est \"insufficient_data\".")
    discrepancyUnit: str | None
    toleranceApplied: float | None = Field(description="Seuil de tolérance effectivement utilisé pour ce calcul (issu de la dérogation station ou, à défaut, du défaut réseau) — permet d'auditer a posteriori quel seuil a produit le statut.")
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
    taxId: str | None = Field(default=None, max_length=50)

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
    taxId: str | None = Field(default=None, max_length=50)
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
    taxId: str | None = None
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
    carrierId: uuid.UUID | None = Field(default=None, description="Transporteur propriétaire/affréteur du camion. Optionnel : un camion peut être créé avant d'être rattaché à un transporteur.")
    plateNumber: str = Field(min_length=1, max_length=50)
    capacityLiters: float | None = Field(default=None, gt=0)
    compartmentsCount: int | None = Field(default=None, gt=0, le=20, description="Nombre de compartiments de la citerne (chaque compartiment peut transporter un produit différent) — plafonné à 20.")


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


# Schémas GPS/tracking (CreateGpsDeviceRequest, GpsDeviceResponse,
# TraccarConnection*, CreateTrackingLocationRequest, TrackingLocationResponse,
# TruckStopReconciliation*, TruckStopComment*, TrackingSettings*,
# IngestTruckPositionRequest, TruckPositionPingResponse,
# TruckStopEventResponse, TruckCurrentPositionResponse) — déplacés vers
# `app/location/schemas.py` (2026-09-15, Phase 2).


class TruckOrderAssignmentRequest(BaseModel):
    truckId: uuid.UUID


class TruckOrderAssignmentResponse(BaseModel):
    id: uuid.UUID
    truckId: uuid.UUID
    purchaseOrderId: uuid.UUID
    active: bool = Field(description="False si l'assignation a été retirée (`DELETE /purchase-orders/{purchase_order_id}/trucks/{truck_id}`) — l'historique des assignations est conservé, pas supprimé.")

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


class GeneratePurchaseOrderDocumentRequest(BaseModel):
    format: Literal["pdf", "docx"]


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


class ChangeStationStaffRoleRequest(BaseModel):
    """Remplace, pour ce membre du personnel, l'attribution de rôle scopée à
    sa station d'affectation — jamais une attribution organisation entière
    (voir `change_station_staff_role`, qui réutilise `assign_role`/
    `unassign_role` du RBAC générique avec la même protection anti-escalade
    de privilèges)."""

    roleId: uuid.UUID


class ResetStationStaffPasswordResponse(BaseModel):
    """Même contrat que `CreateStationStaffResponse.temporaryPassword` : le
    mot de passe temporaire n'apparaît qu'ici, une seule fois, jamais stocké
    en clair ni rejouable ensuite."""

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
    stockQuantity: float = Field(default=0, ge=0)
    lowStockThreshold: float | None = Field(default=None, ge=0)


class UpdateSellableProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=60)
    barcodeValue: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=60)
    unitPriceAmount: float | None = Field(default=None, gt=0)
    active: bool | None = None
    stockQuantity: float | None = Field(default=None, ge=0)
    lowStockThreshold: float | None = Field(default=None, ge=0)


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
    stockQuantity: float
    lowStockThreshold: float | None

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
