import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_liquid.models import FuelProduct
from app.modules.zylo_liquid.schemas import CreateFuelProductRequest, UpdateFuelProductRequest


async def create_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, data: CreateFuelProductRequest
) -> FuelProduct:
    existing = await db.execute(
        select(FuelProduct).where(
            FuelProduct.organizationId == organization_id, FuelProduct.code == data.code
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(
            code="fuel_product_code_already_used",
            message=f"Un produit carburant avec le code '{data.code}' existe déjà pour cette organisation.",
            status_code=409,
        )

    fuel_product = FuelProduct(organizationId=organization_id, **data.model_dump())
    db.add(fuel_product)
    await db.commit()
    await db.refresh(fuel_product)
    return fuel_product


async def get_fuel_product(db: AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID) -> FuelProduct:
    result = await db.execute(
        select(FuelProduct).where(
            FuelProduct.id == fuel_product_id, FuelProduct.organizationId == organization_id
        )
    )
    fuel_product = result.scalar_one_or_none()
    if fuel_product is None:
        raise AppError(code="fuel_product_not_found", message="Produit carburant introuvable.", status_code=404)
    return fuel_product


async def update_fuel_product(
    db: AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID, data: UpdateFuelProductRequest
) -> FuelProduct:
    fuel_product = await get_fuel_product(db, organization_id, fuel_product_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fuel_product, field, value)
    await db.commit()
    await db.refresh(fuel_product)
    return fuel_product
