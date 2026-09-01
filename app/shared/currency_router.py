import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.rbac.service import require_permission
from app.shared import currency_service as service
from app.shared.currency import Currency, ExchangeRate
from app.shared.currency_schemas import (
    CreateCurrencyRequest,
    CreateExchangeRateRequest,
    CurrencyResponse,
    ExchangeRateResponse,
    UpdateCurrencyRequest,
)
from app.shared.pagination import PaginationParams, paginate
from app.shared.permissions import CURRENCY_MANAGE, CURRENCY_READ, EXCHANGE_RATE_MANAGE, EXCHANGE_RATE_READ
from app.shared.schemas import Page

currency_router = APIRouter()
exchange_rate_router = APIRouter()


@currency_router.get("", response_model=Page[CurrencyResponse], dependencies=[Depends(require_permission(CURRENCY_READ))])
async def list_currencies(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)) -> Page:
    return await paginate(db, select(Currency).order_by(Currency.code), pagination, CurrencyResponse)


@currency_router.post("", response_model=CurrencyResponse, status_code=201, dependencies=[Depends(require_permission(CURRENCY_MANAGE))])
async def create_currency(data: CreateCurrencyRequest, db: AsyncSession = Depends(get_db)) -> Currency:
    return await service.create_currency(db, data)


@currency_router.patch("/{currency_id}", response_model=CurrencyResponse, dependencies=[Depends(require_permission(CURRENCY_MANAGE))])
async def update_currency(currency_id: uuid.UUID, data: UpdateCurrencyRequest, db: AsyncSession = Depends(get_db)) -> Currency:
    return await service.update_currency(db, currency_id, data)


@exchange_rate_router.get("", response_model=Page[ExchangeRateResponse], dependencies=[Depends(require_permission(EXCHANGE_RATE_READ))])
async def list_exchange_rates(
    pagination: PaginationParams = Depends(),
    sourceCurrencyId: uuid.UUID | None = None,
    targetCurrencyId: uuid.UUID | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> Page:
    stmt = select(ExchangeRate)
    if sourceCurrencyId is not None:
        stmt = stmt.where(ExchangeRate.sourceCurrencyId == sourceCurrencyId)
    if targetCurrencyId is not None:
        stmt = stmt.where(ExchangeRate.targetCurrencyId == targetCurrencyId)
    if fromDate is not None:
        stmt = stmt.where(ExchangeRate.effectiveFrom >= fromDate)
    if toDate is not None:
        stmt = stmt.where(ExchangeRate.effectiveFrom <= toDate)
    stmt = stmt.order_by(ExchangeRate.effectiveFrom.desc())
    return await paginate(db, stmt, pagination, ExchangeRateResponse)


@exchange_rate_router.post(
    "", response_model=ExchangeRateResponse, status_code=201, dependencies=[Depends(require_permission(EXCHANGE_RATE_MANAGE))]
)
async def create_exchange_rate(data: CreateExchangeRateRequest, db: AsyncSession = Depends(get_db)) -> ExchangeRate:
    return await service.create_exchange_rate(db, data)
