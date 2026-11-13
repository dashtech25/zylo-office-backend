"""Gardes de portée des routes zylo_liquid : résolvent la station (ou la ressource) visée
par une requête, pour `require_permission_scoped_via*`.

Les helpers `_tank_station_scope` à `_price_station_scope` étaient dans `router.py` (remy) ; ils sont
déplacés ici à l'identique pour être partagés par les routeurs des sous-domaines (`shifts/`, `pumps/`,
`jauge/`, `caisse/`, `rapport/`, `personnel/`) sans cycle : aucun de ces modules n'importe `router.py`.
"""

import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.models import Pump, StationStaffProfile
from app.rbac.service import get_current_organization_id, user_has_permission
import uuid
from app.modules.zylo_liquid.models import StationStaffProfile
from app.modules.zylo_liquid.exploitation import pumps_affectation as pumps_affectation
from app.modules.zylo_liquid.exploitation import shifts_attendance as shifts_attendance
from app.modules.zylo_liquid.exploitation import shifts_passation as shifts_passation
from app.modules.zylo_liquid.exploitation import shifts_rapport as shifts_rapport
from app.modules.zylo_liquid.stations import service as stations_service
from app.modules.zylo_liquid.tanks import service as tanks_service
from app.modules.zylo_liquid import service as zylo_service


async def _tank_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Une cuve n'a pas de portée propre dans le modèle de grants (§10.3 du
    document d'architecture RBAC) : la portée utile est celle de SA station
    (ex. « le chef d'équipe reçoit Cuve Diesel » = un grant scopé à la
    station qui la contient), jamais la cuve isolément."""
    raw_id = path_params.get("tank_id")
    if raw_id is None:
        return None, None
    tank = await tanks_service.get_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", tank.stationId


async def _pump_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Une pompe n'a pas de portée propre : même principe que `_tank_station_scope`."""
    raw_id = path_params.get("pump_id")
    if raw_id is None:
        return None, None
    pump = await tanks_service.get_pump(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", pump.stationId


async def _station_id_body_scope(db: AsyncSession, organization_id: uuid.UUID, body: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée pour un POST de création dont le corps porte directement
    `stationId` (cuve, pompe, produit rattaché à une station) — voir
    `require_permission_scoped_via_body`."""
    raw_id = body.get("stationId")
    if raw_id is None:
        return None, None
    return "station", uuid.UUID(str(raw_id))


async def _tank_id_body_scope(db: AsyncSession, organization_id: uuid.UUID, body: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée pour un POST de création dont le corps porte `tankId` (ex.
    rattachement d'un capteur Holykell) — résolue via la station de CETTE
    cuve, même principe que `_tank_station_scope`."""
    raw_id = body.get("tankId")
    if raw_id is None:
        return None, None
    tank = await tanks_service.get_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", tank.stationId


async def _tank_sensor_mapping_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Un rattachement capteur n'a pas de portée propre : résolue via la
    station de sa cuve, même principe que `_tank_station_scope`."""
    raw_id = path_params.get("mapping_id")
    if raw_id is None:
        return None, None
    mapping = await tanks_service.get_tank_sensor_mapping(db, organization_id, uuid.UUID(str(raw_id)))
    tank = await tanks_service.get_tank(db, organization_id, mapping.tankId)
    return "station", tank.stationId


async def _station_id_query_scope(db: AsyncSession, organization_id: uuid.UUID, query_params) -> tuple[str | None, uuid.UUID | None]:
    """Portée pour un GET de liste filtrable par `?stationId=` — voir
    `require_permission_scoped_via_query`."""
    raw_id = query_params.get("stationId")
    if raw_id is None:
        return None, None
    return "station", uuid.UUID(str(raw_id))


async def _occurrence_id_query_scope(db: AsyncSession, organization_id: uuid.UUID, query_params) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'un tour (`?occurrenceId=`, B1/B2) : résolue via la station de l'occurrence,
    jamais seulement la permission globale."""
    raw_id = query_params.get("occurrenceId")
    if raw_id is None:
        return None, None
    occurrence = await shifts_attendance.get_occurrence_by_id(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", occurrence.stationId


async def _occurrence_id_body_scope(db: AsyncSession, organization_id: uuid.UUID, body: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'un tour dont l'identifiant arrive dans le corps JSON (`occurrenceId`, B1/B2)."""
    raw_id = body.get("occurrenceId")
    if raw_id is None:
        return None, None
    occurrence = await shifts_attendance.get_occurrence_by_id(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", occurrence.stationId


async def _handover_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'une passation (`/shift-handover/{handover_id}/...`)."""
    raw_id = path_params.get("handover_id")
    if raw_id is None:
        return None, None
    return "station", await shifts_passation.get_handover_station_id(db, organization_id, uuid.UUID(str(raw_id)))


async def _handover_item_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'une ligne de passation (`/shift-handover/items/{item_id}/...`)."""
    raw_id = path_params.get("item_id")
    if raw_id is None:
        return None, None
    return "station", await shifts_passation.get_handover_item_station_id(db, organization_id, uuid.UUID(str(raw_id)))


async def _pump_assignment_report_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'un rapport de tour (`/shift-reports/{report_id}/assignments`, B4) : résolue via la station du tour."""
    raw_id = path_params.get("report_id")
    if raw_id is None:
        return None, None
    return "station", await pumps_affectation.get_pump_assignment_station_id(db, organization_id, uuid.UUID(str(raw_id)))


async def _tank_id_query_scope(db: AsyncSession, organization_id: uuid.UUID, query_params) -> tuple[str | None, uuid.UUID | None]:
    """Portée pour un GET de liste filtrable par `?tankId=` — résolue via la
    station de cette cuve, même principe que `_tank_station_scope`."""
    raw_id = query_params.get("tankId")
    if raw_id is None:
        return None, None
    tank = await tanks_service.get_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", tank.stationId


async def _station_fuel_product_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Une association station/produit n'a pas de portée propre : résolue
    via sa station, même principe que `_tank_station_scope`."""
    raw_id = path_params.get("association_id")
    if raw_id is None:
        return None, None
    association = await stations_service.get_station_fuel_product(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", association.stationId


async def _delivery_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("delivery_id")
    if raw_id is None:
        return None, None
    delivery = await zylo_service.get_delivery(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", delivery.stationId


async def _leak_event_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("leak_event_id")
    if raw_id is None:
        return None, None
    leak_event = await zylo_service.get_leak_event(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", leak_event.stationId


async def _price_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Un prix par défaut réseau (`stationId IS NULL`, Phase 1 §1.3 de
    refonte-configuration-zylo-liquid.md) n'a pas de station à laquelle
    rattacher la portée — `(None, None)` équivaut alors à une vérification
    org entière (comportement inchangé pour ces lignes)."""
    raw_id = path_params.get("price_id")
    if raw_id is None:
        return None, None
    price = await zylo_service._get_price_history_and_station(db, organization_id, uuid.UUID(str(raw_id)))
    if price.stationId is None:
        return None, None
    return "station", price.stationId


async def _shift_report_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Portée station d'un rapport de tour (`/shift-reports/{report_id}/...`, B3)."""
    raw_id = path_params.get("report_id")
    if raw_id is None:
        return None, None
    return "station", await shifts_rapport.get_shift_report_station_id(db, organization_id, uuid.UUID(str(raw_id)))


async def _staff_user_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    """Un membre du personnel n'a pas de portée propre : la portée est la station de sa fiche.
    Sans fiche, (None, None) : la garde redevient organisation entière (refus pour un gérant de station)."""
    raw_id = path_params.get("user_id")
    if raw_id is None:
        return None, None
    profile = (await db.execute(select(StationStaffProfile).where(
        StationStaffProfile.organizationId == organization_id, StationStaffProfile.userId == uuid.UUID(str(raw_id))
    ))).scalar_one_or_none()
    if profile is None or profile.assignedStationId is None:
        return None, None
    return "station", profile.assignedStationId


def require_permission_scoped_via_body(permission_code: str, resolve_scope):
    """Garde de permission scopée à une ressource désignée DANS LE CORPS JSON
    (création d'une pompe, d'une cuve... rattachée à `stationId`).

    Logique identique à `app/rbac/service.py` (version du snapshot). Définie ici et non
    dans rbac/service.py : ce fichier relève du lot B-L5, non intégré dans T-004b lot B-L2."""

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        body = await request.json()
        resource_type, resource_id = await resolve_scope(db, organization_id, body)
        allowed = await user_has_permission(db, current_user.id, organization_id, permission_code, resource_type, resource_id)
        if not allowed:
            raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)

    return dependency


def require_permission_scoped_via_query(permission_code: str, resolve_scope):
    """Garde scopée à partir des paramètres de requête (GET de liste). Sans valeur, la
    vérification redevient organisation entière : jamais un blocage silencieux."""

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        resource_type, resource_id = await resolve_scope(db, organization_id, request.query_params)
        allowed = await user_has_permission(db, current_user.id, organization_id, permission_code, resource_type, resource_id)
        if not allowed:
            raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)

    return dependency
