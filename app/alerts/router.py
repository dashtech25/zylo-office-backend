"""Routes du module Alertes (capacité partagée) — extraites de
`app/modules/zylo_liquid/router.py` (2026-09-15, Phase 3 de la migration
monolithe modulaire, voir ARCHITECTURE.md). Montées sous le même préfixe
`/zylo-liquid` que précédemment (voir `app/api/v1/router.py`) : le
déplacement du code entre modules Python ne doit jamais casser une URL
déjà consommée par le frontend."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import service
from app.alerts.permissions import ALERT_ACKNOWLEDGE, ALERT_MANAGE, ALERT_READ
from app.alerts.schemas import AlertResponse, ResolveAlertRequest
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.service import require_module_active
from app.rbac.service import get_current_organization_id, require_permission_scoped_via
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page

# Les alertes restent, pour l'instant, une capacité consommée uniquement
# par le module zylo_liquid (toutes les alertes actuelles proviennent de
# ses producteurs, y compris celles de `location` sur un arrêt non
# qualifié, qui dépend elle-même du tracking activé pour zylo_liquid) —
# même garde `require_module_active("zylo_liquid")` qu'avant l'extraction,
# quand ces routes vivaient dans le routeur zylo_liquid. Contrairement à
# Files/Location, ce comportement est vérifié par un test existant
# (`test_list_alerts_without_permission_is_denied`), donc préservé tel
# quel plutôt que silencieusement abandonné par le déplacement de code.
router = APIRouter(dependencies=[Depends(require_module_active("zylo_liquid"))])


async def _alert_station_scope(db: AsyncSession, organization_id: uuid.UUID, path_params: dict) -> tuple[str | None, uuid.UUID | None]:
    raw_id = path_params.get("alert_id")
    if raw_id is None:
        return None, None
    alert, _tank = await service._get_alert_and_tank(db, organization_id, uuid.UUID(str(raw_id)))
    return "station", alert.stationId


@router.get(
    "/alerts",
    response_model=Page[AlertResponse],
    summary="Lister les alertes",
    description="Liste paginée des alertes (fuites suspectées, seuils de niveau, écarts de réconciliation, etc.), filtrable par station, cuve, camion, type et statut sur une plage de dates.",
)
async def list_alerts(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    truckId: uuid.UUID | None = None,
    tankId: uuid.UUID | None = None,
    type: str | None = None,
    status: str | None = None,
    fromDate: datetime | None = None,
    toDate: datetime | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Pas de `require_permission(ALERT_READ)` global — même principe que
    `list_stations`/`list_deliveries`/`list_leak_events`."""
    return await service.list_alerts(db, organization_id, current_user.id, pagination, stationId, tankId, type, status, fromDate, toDate, truckId)


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission_scoped_via(ALERT_READ, _alert_station_scope))],
    summary="Détail d'une alerte",
    description="Retourne une alerte par son identifiant, avec son type, son statut courant et, si applicable, qui l'a acquittée/résolue et quand.",
)
async def get_alert(
    alert_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    return await service.get_alert(db, organization_id, alert_id)


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission_scoped_via(ALERT_ACKNOWLEDGE, _alert_station_scope))],
    summary="Acquitter une alerte (« je m'en occupe »)",
    description=(
        "Marque l'alerte comme prise en charge par l'utilisateur courant, sans la clôturer : "
        "l'acquittement signale juste qu'un traitement est en cours. Pour clôturer réellement "
        "l'alerte, utiliser `PATCH /alerts/{alert_id}` (résolution manuelle, réservée aux types "
        "d'alerte sans vérification automatique)."
    ),
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """D3 : « je m'en occupe » — ne referme jamais l'alerte (voir PATCH pour
    la résolution manuelle, réservée aux types sans vérification auto)."""
    return await service.acknowledge_alert(db, organization_id, current_user.id, alert_id)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission_scoped_via(ALERT_MANAGE, _alert_station_scope))],
    summary="Résoudre manuellement une alerte",
    description=(
        "Clôture une alerte en indiquant une note de résolution obligatoire. Réservé aux types "
        "d'alerte qui n'ont pas de vérification automatique de fin de condition : pour un type "
        "auto-vérifiable (ex. un seuil qui repasse sous la limite tout seul), le service refuse la "
        "requête avec un 422 — la résolution doit passer par le contrôle automatique, pas manuellement."
    ),
)
async def resolve_alert(
    alert_id: uuid.UUID,
    data: ResolveAlertRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """D2 : réservé aux types sans vérification automatique possible — le
    service refuse la requête (422) pour un type auto-vérifiable."""
    return await service.resolve_alert(db, organization_id, current_user.id, alert_id, data.resolutionNote)
