"""Garde des tours ouverts : questions de lecture utilisées par les autres sous-domaines
(désactivation d'une pompe ou d'une cuve, changement de cuve, dernier relevé d'une pompe ou d'une cuve).

Module feuille : il n'importe que les modèles et AppError. C'est ce qui permet à `tanks/service.py`
(et donc à `service.py`) de consulter les tours ouverts sans cycle avec le domaine d'exploitation.
Les fonctions sont reprises à l'identique de `exploitation/shifts_rapport.py` (T-004b lot B-L2).
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_liquid.models import Pump, ShiftOccurrence, ShiftReport, ShiftReportPumpLine, ShiftReportTankLine, Station, Tank


async def get_open_report(db: AsyncSession, station_id: uuid.UUID) -> ShiftReport | None:
    """Rapport du tour ouvert de la station, ou None."""
    return (await db.execute(
        select(ShiftReport).join(ShiftOccurrence, ShiftOccurrence.id == ShiftReport.occurrenceId)
        .where(ShiftReport.stationId == station_id, ShiftOccurrence.status == "opened")
    )).scalar_one_or_none()



async def get_open_occurrence(db: AsyncSession, station_id: uuid.UUID) -> ShiftOccurrence | None:
    """Le tour `opened` de la station (il n'y en a jamais plus d'un : index unique partiel)."""
    return (await db.execute(select(ShiftOccurrence).where(ShiftOccurrence.stationId == station_id, ShiftOccurrence.status == "opened"))).scalar_one_or_none()



async def get_open_shift_for_pump(db: AsyncSession, pump_id: uuid.UUID) -> ShiftOccurrence | None:
    """Tour ouvert dont le rapport contient une ligne pour cette pompe, ou None."""
    return (await db.execute(
        select(ShiftOccurrence)
        .join(ShiftReport, ShiftReport.occurrenceId == ShiftOccurrence.id)
        .join(ShiftReportPumpLine, ShiftReportPumpLine.reportId == ShiftReport.id)
        .where(ShiftReportPumpLine.pumpId == pump_id, ShiftOccurrence.status == "opened")
    )).scalars().first()



async def is_pump_in_open_shift(db: AsyncSession, pump_id: uuid.UUID) -> bool:
    return await get_open_shift_for_pump(db, pump_id) is not None



async def get_open_shift_for_tank(db: AsyncSession, tank_id: uuid.UUID) -> ShiftOccurrence | None:
    """Tour ouvert dont le rapport contient une ligne pour cette cuve, ou None."""
    return (await db.execute(
        select(ShiftOccurrence)
        .join(ShiftReport, ShiftReport.occurrenceId == ShiftOccurrence.id)
        .join(ShiftReportTankLine, ShiftReportTankLine.reportId == ShiftReport.id)
        .where(ShiftReportTankLine.tankId == tank_id, ShiftOccurrence.status == "opened")
    )).scalars().first()



async def get_last_closing_for_pump(db: AsyncSession, pump_id: uuid.UUID) -> tuple[ShiftReportPumpLine, ShiftOccurrence] | None:
    """Dernière fermeture CONNUE de la pompe : ligne d'un tour clos/validé qui a un index de fermeture
    (écrit par D1), la plus récente d'abord. Source du report de l'index d'ouverture du tour suivant."""
    row = (await db.execute(
        select(ShiftReportPumpLine, ShiftOccurrence)
        .join(ShiftReport, ShiftReport.id == ShiftReportPumpLine.reportId)
        .join(ShiftOccurrence, ShiftOccurrence.id == ShiftReport.occurrenceId)
        .where(ShiftReportPumpLine.pumpId == pump_id, ShiftReportPumpLine.closingIndex.is_not(None), ShiftOccurrence.status.in_(("closed", "validated")))
        .order_by(ShiftOccurrence.startsAt.desc(), ShiftReportPumpLine.createdAt.desc())
        .limit(1)
    )).first()
    return (row[0], row[1]) if row else None



async def get_last_real_stock_for_tank(db: AsyncSession, tank_id: uuid.UUID) -> tuple[ShiftReportTankLine, ShiftOccurrence] | None:
    """Dernier stock RÉEL de fermeture connu de la cuve (litres, écrit par D2) d'un tour clos/validé."""
    row = (await db.execute(
        select(ShiftReportTankLine, ShiftOccurrence)
        .join(ShiftReport, ShiftReport.id == ShiftReportTankLine.reportId)
        .join(ShiftOccurrence, ShiftOccurrence.id == ShiftReport.occurrenceId)
        .where(ShiftReportTankLine.tankId == tank_id, ShiftReportTankLine.closingRealStockLiters.is_not(None), ShiftOccurrence.status.in_(("closed", "validated")))
        .order_by(ShiftOccurrence.startsAt.desc(), ShiftReportTankLine.createdAt.desc())
        .limit(1)
    )).first()
    return (row[0], row[1]) if row else None



def _station_zone(station: Station) -> ZoneInfo:
    try:
        return ZoneInfo(station.timezone or "Africa/Douala")
    except Exception:
        return ZoneInfo("Africa/Douala")



def _opened_local_time(opened_at: datetime, station: Station) -> str:
    return opened_at.astimezone(_station_zone(station)).strftime("%H:%M")



def _open_shift_blocking_label(occurrence: ShiftOccurrence, station: Station) -> str:
    since = _opened_local_time(occurrence.openedAt, station) if occurrence.openedAt else None
    return f"« {occurrence.name} » ouvert depuis {since}" if since else f"« {occurrence.name} » ouvert"



async def assert_pump_can_be_deactivated(db: AsyncSession, pump: Pump) -> None:
    """Garde A1/D3 réalisée par B3 : une pompe utilisée par un tour OUVERT ne se désactive pas."""
    occurrence = await get_open_shift_for_pump(db, pump.id)
    if occurrence is not None:
        station = await db.get(Station, pump.stationId)
        raise AppError(
            code="pump_in_open_shift",
            message=(
                f"La pompe N° {pump.pumpNumber} est utilisée par le tour {_open_shift_blocking_label(occurrence, station)}. Fermez le tour avant de la désactiver. "
                "Si elle est en panne, déclarez la panne (mise hors service temporaire) plutôt que de la désactiver."
            ),
            status_code=409,
            details=[{"occurrenceId": str(occurrence.id), "pumpId": str(pump.id)}],
        )



async def assert_pump_tank_can_change(db: AsyncSession, pump: Pump) -> None:
    """Garde B3 : changer la cuve d'une pompe changerait le produit en cours de tour."""
    occurrence = await get_open_shift_for_pump(db, pump.id)
    if occurrence is not None:
        station = await db.get(Station, pump.stationId)
        raise AppError(
            code="pump_tank_locked_in_open_shift",
            message=(
                f"La pompe N° {pump.pumpNumber} est en service dans le tour {_open_shift_blocking_label(occurrence, station)} : changer sa cuve changerait le produit en cours de tour. "
                "Fermez le tour, puis modifiez la cuve."
            ),
            status_code=409,
            details=[{"occurrenceId": str(occurrence.id), "pumpId": str(pump.id)}],
        )

