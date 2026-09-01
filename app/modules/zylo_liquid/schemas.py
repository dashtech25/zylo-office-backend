import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CreateFuelProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=10)
    densityGPerCm3: float | None = None
    thermalExpansionCoefficient: float | None = None
    currentPriceFcfa: float | None = None
    currentCostFcfa: float | None = None
    displayColor: str | None = Field(default=None, max_length=7)


class UpdateFuelProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    densityGPerCm3: float | None = None
    thermalExpansionCoefficient: float | None = None
    currentPriceFcfa: float | None = None
    currentCostFcfa: float | None = None
    displayColor: str | None = Field(default=None, max_length=7)
    active: bool | None = None


class FuelProductResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    code: str
    densityGPerCm3: float | None
    thermalExpansionCoefficient: float | None
    currentPriceFcfa: float | None
    currentCostFcfa: float | None
    displayColor: str | None
    active: bool

    model_config = {"from_attributes": True}


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
    notes: str | None = None


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
    notes: str | None = None


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
    status: str
    integrationDate: date | None
    notes: str | None
    activeTankCount: int = 0

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


class TankSensorMappingResponse(BaseModel):
    id: uuid.UUID
    hkSensorId: int
    tankId: uuid.UUID
    measurementType: str
    validFrom: datetime
    validUntil: datetime | None
    active: bool

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
    waterHeightMm: float | None
    waterVolumeLiters: float | None
    temperatureC: float | None
    emptyVolumeLiters: float | None
    lastMeasurementAt: datetime | None


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


class HolykellAccountSyncStatusResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    lastSyncAt: datetime | None
    lastSyncStatus: str | None
    lastSyncError: str | None
    syncEnabled: bool

    model_config = {"from_attributes": True}
