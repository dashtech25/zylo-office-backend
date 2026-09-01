import uuid

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
