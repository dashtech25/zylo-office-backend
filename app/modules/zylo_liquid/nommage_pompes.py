"""Nommage et numérotation des pompes (scénario A1).

Le numéro est unique par station ; le nom généré « Pompe N° {n} – {produit} » est figé en base et resynchronisé quand le numéro, la cuve ou le produit changent. Module sans import de stations/ ni tanks/ (pas de cycle)."""

import uuid
from app.core.errors import AppError
from app.modules.zylo_liquid.models import FuelProduct, Pump, Tank
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _generated_pump_name(pump_number: int, fuel_product_name: str) -> str:
    """Nom généré (jamais saisi) : « Pompe N° 3 – Super ». Figé en base pour
    garantir l'unicité par station et la stabilité de l'import Excel des
    ventes (qui retrouve la pompe par son nom)."""
    return f"Pompe N° {pump_number} – {fuel_product_name}"









async def _resync_pump_names(
    db: AsyncSession, *, tank_id: uuid.UUID | None = None, fuel_product_id: uuid.UUID | None = None
) -> None:
    """Régénère le nom des pompes d'une cuve (changement de produit de la
    cuve) ou de toutes les pompes dont la cuve porte un produit (produit
    renommé). Appelé dans la MÊME transaction que le changement déclencheur :
    le nom figé en base ne doit jamais rester périmé. L'unicité par station
    est préservée car le numéro, unique par station, fait partie du nom."""
    await db.flush()
    stmt = (
        select(Pump, FuelProduct.name)
        .join(Tank, Tank.id == Pump.tankId)
        .join(FuelProduct, FuelProduct.id == Tank.fuelProductId)
    )
    if tank_id is not None:
        stmt = stmt.where(Pump.tankId == tank_id)
    if fuel_product_id is not None:
        stmt = stmt.where(Tank.fuelProductId == fuel_product_id)
    for pump, product_name in (await db.execute(stmt)).all():
        new_name = _generated_pump_name(pump.pumpNumber, product_name)
        if pump.name != new_name:
            pump.name = new_name
    await db.flush()



async def _next_free_pump_number(db: AsyncSession, station_id: uuid.UUID) -> int:
    highest = await db.scalar(select(func.max(Pump.pumpNumber)).where(Pump.stationId == station_id))
    return (highest or 0) + 1




async def _assert_pump_number_free(db: AsyncSession, station_id: uuid.UUID, pump_number: int, exclude_pump_id: uuid.UUID | None = None) -> None:
    stmt = select(Pump.name).where(Pump.stationId == station_id, Pump.pumpNumber == pump_number)
    if exclude_pump_id is not None:
        stmt = stmt.where(Pump.id != exclude_pump_id)
    existing_name = await db.scalar(stmt)
    if existing_name is not None:
        raise AppError(
            code="pump_number_taken",
            message=f"Le numéro {pump_number} est déjà utilisé par « {existing_name} ». Choisissez un autre numéro.",
            status_code=409,
        )
