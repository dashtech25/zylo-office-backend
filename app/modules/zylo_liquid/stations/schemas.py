"""Schémas Pydantic des stations : requêtes et réponses des stations, services, politique de prix et produits carburant de station.

Les classes sont réexportées par `zylo_liquid/schemas.py` (anciens chemins inchangés). Ce module
n'importe jamais `zylo_liquid/schemas.py` (cycle). Les schémas des cuves sont dans `tanks/schemas.py`.
"""

import colorsys
import uuid
from datetime import date, timezone
from pydantic import BaseModel, Field, field_validator


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


class DayHours(BaseModel):
    """Horaires d'un jour donné (P2 §5.3, audit module Stations
    2026-09-16). `closed=True` ferme ce jour indépendamment de
    `closedWeekdays` (les deux mécanismes ne se combinent jamais — voir
    `weeklyHours` sur `Station`)."""

    open: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    close: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    closed: bool = False


def _validate_weekly_hours(value: dict[str, DayHours] | None) -> dict[str, DayHours] | None:
    if value is None:
        return None
    if not value:
        return None
    invalid_keys = set(value.keys()) - {str(d) for d in range(1, 8)}
    if invalid_keys:
        raise ValueError("weeklyHours doit être indexé par jour ISO (\"1\"=lundi..\"7\"=dimanche).")
    return value


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
    weeklyHours: dict[str, DayHours] | None = Field(default=None, description="Horaires personnalisés par jour (clé \"1\"=lundi..\"7\"=dimanche). `None` = pas de personnalisation, openingTime/closingTime/closedWeekdays ci-dessus s'appliquent à tous les jours ouverts.")
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
    _validate_weekly_hours = field_validator("weeklyHours")(_validate_weekly_hours)


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
    weeklyHours: dict[str, DayHours] | None = None
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
    _validate_weekly_hours = field_validator("weeklyHours")(_validate_weekly_hours)


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
    weeklyHours: dict[str, DayHours] | None = None
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
