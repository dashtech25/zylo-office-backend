from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.shared.currency import Currency, ExchangeRate
from app.shared.currency_schemas import CreateCurrencyRequest, CreateExchangeRateRequest, UpdateCurrencyRequest
from app.shared.simple_cache import TTLCache

# Cache TTL 60s pour la liste des devises — référentiel global (pas de
# organizationId sur `Currency`, vérifié), quasi statique (Phase 1 audit,
# problème #3). Une seule clé par combinaison pagination, pas de scoping
# par organisation. Invalidé explicitement par create_currency/
# update_currency ci-dessous.
currency_list_cache = TTLCache(default_ttl_seconds=60.0)


async def create_currency(db: AsyncSession, data: CreateCurrencyRequest) -> Currency:
    existing = await db.execute(select(Currency).where(Currency.code == data.code))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="currency_code_already_used", message=f"La devise '{data.code}' existe déjà.", status_code=409)
    currency = Currency(**data.model_dump())
    db.add(currency)
    await db.commit()
    await db.refresh(currency)
    currency_list_cache.clear()
    return currency


async def get_currency(db: AsyncSession, currency_id) -> Currency:
    result = await db.execute(select(Currency).where(Currency.id == currency_id))
    currency = result.scalar_one_or_none()
    if currency is None:
        raise AppError(code="currency_not_found", message="Devise introuvable.", status_code=404)
    return currency


async def update_currency(db: AsyncSession, currency_id, data: UpdateCurrencyRequest) -> Currency:
    currency = await get_currency(db, currency_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(currency, field, value)
    await db.commit()
    await db.refresh(currency)
    currency_list_cache.clear()
    return currency


async def create_exchange_rate(db: AsyncSession, data: CreateExchangeRateRequest) -> ExchangeRate:
    if data.sourceCurrencyId == data.targetCurrencyId:
        raise AppError(
            code="exchange_rate_same_currency",
            message="La devise source et la devise cible doivent être différentes.",
            status_code=422,
        )
    await get_currency(db, data.sourceCurrencyId)
    await get_currency(db, data.targetCurrencyId)

    existing = await db.execute(
        select(ExchangeRate).where(
            ExchangeRate.sourceCurrencyId == data.sourceCurrencyId,
            ExchangeRate.targetCurrencyId == data.targetCurrencyId,
            ExchangeRate.effectiveFrom == data.effectiveFrom,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="exchange_rate_already_exists",
            message="Un taux existe déjà pour cette paire de devises à cette date de début.",
            status_code=409,
        )

    exchange_rate = ExchangeRate(**data.model_dump())
    db.add(exchange_rate)
    await db.commit()
    await db.refresh(exchange_rate)
    return exchange_rate
