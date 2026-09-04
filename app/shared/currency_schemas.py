import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateCurrencyRequest(BaseModel):
    code: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=10)
    decimalPlaces: int = Field(default=2, ge=0, le=4)


class UpdateCurrencyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    symbol: str | None = Field(default=None, min_length=1, max_length=10)
    decimalPlaces: int | None = Field(default=None, ge=0, le=4)
    active: bool | None = None


class CurrencyResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    symbol: str
    decimalPlaces: int
    active: bool

    model_config = {"from_attributes": True}


class CreateExchangeRateRequest(BaseModel):
    sourceCurrencyId: uuid.UUID
    targetCurrencyId: uuid.UUID
    rate: float = Field(gt=0)
    effectiveFrom: datetime


class ExchangeRateResponse(BaseModel):
    id: uuid.UUID
    sourceCurrencyId: uuid.UUID
    targetCurrencyId: uuid.UUID
    rate: float
    effectiveFrom: datetime

    model_config = {"from_attributes": True}
