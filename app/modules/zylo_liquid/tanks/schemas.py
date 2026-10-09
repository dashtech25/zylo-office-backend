"""Schémas Pydantic des cuves : cuves, pompes, correspondances capteurs, calibration.

Les classes sont réexportées par `zylo_liquid/schemas.py`. Ce module n'importe jamais
`zylo_liquid/schemas.py` (cycle) ; il peut importer `stations/schemas.py`.
"""

import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field


class CreateTankRequest(BaseModel):
    stationId: uuid.UUID
    tankNumber: int | None = Field(default=None, gt=0, description="Numéro de cuve au sein de la station — optionnel : si absent, le système attribue automatiquement le prochain numéro disponible (jamais à l'utilisateur de le deviner par essai-erreur). Fourni explicitement seulement pour un usage programmatique/import qui a besoin d'imposer un numéro précis.")
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


class CreatePumpRequest(BaseModel):
    """Le nom n'est jamais saisi : il est généré par le backend (« Pompe N°
    {pumpNumber} – {produit de la cuve} »). Sans `pumpNumber`, le prochain
    numéro libre de la station est attribué."""

    stationId: uuid.UUID
    tankId: uuid.UUID
    pumpNumber: int | None = Field(default=None, gt=0, le=32767)
    brand: str | None = Field(default=None, max_length=100)
    serialNumber: str | None = Field(default=None, max_length=100)
    installedOn: date | None = None


class UpdatePumpRequest(BaseModel):
    tankId: uuid.UUID | None = None
    pumpNumber: int | None = Field(default=None, gt=0, le=32767)
    brand: str | None = Field(default=None, max_length=100)
    serialNumber: str | None = Field(default=None, max_length=100)
    installedOn: date | None = None
    active: bool | None = None


class PumpResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID
    tankId: uuid.UUID
    name: str
    active: bool
    pumpNumber: int
    brand: str | None = None
    serialNumber: str | None = None
    installedOn: date | None = None
    fuelProductId: uuid.UUID
    fuelProductName: str


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
