import uuid
from datetime import date

from pydantic import BaseModel, Field


class CreateFuelProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=10)
    densityGPerCm3: float | None = None
    currentPriceFcfa: float | None = None
    currentCostFcfa: float | None = None
    displayColor: str | None = Field(default=None, max_length=7)


class UpdateFuelProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    densityGPerCm3: float | None = None
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
