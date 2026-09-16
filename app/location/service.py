"""Service du module Location (tracking GPS des camions-citernes) —
extrait de `app/modules/zylo_liquid/service.py` (2026-09-15, Phase 2 de
la migration monolithe modulaire). Logique inchangée, seul l'emplacement
bouge — voir `ARCHITECTURE.md` pour le plan complet.

Dépendance délibérée et documentée vers `app.modules.zylo_liquid` (pas
l'inverse) : `Truck`/`TRUCK_READ` restent dans zylo_liquid (le véhicule
lui-même est un objet métier carburant, pas une donnée de localisation).
`TruckPositionPing`/`GpsDeviceAssignment`/`TruckStopEvent` gardent eux
aussi une FK stricte vers `zyloLiquidTruck.id` (voir
`app/location/models.py`).

`_qualify_truck_stop` publie l'événement de domaine `TruckStopUnqualified`
(`app.shared.events.publish`, Phase 5) sur l'arrêt non qualifié (scénario
6), au lieu d'appeler directement `app.alerts.service.upsert_active_alert`
comme le faisait la Phase 3 (2026-09-15) — et avant elle, jusqu'à la
Phase 3, ce fichier construisait même `Alert` directement (import de
`app.modules.zylo_liquid.models`). C'est le premier cas d'usage réel du
registre d'événements : Location n'a plus besoin de connaître
`app.alerts.service` du tout pour ce cas précis (aucun import
`from app.alerts import service` restant dans ce fichier), la
dépendance devient un simple nom d'événement partagé — voir
`app.alerts.service.handle_truck_stop_unqualified`, le handler abonné
(inscription dans `app/main.py`).

`run_truck_stop_detection` ne publie l'événement qu'APRÈS son propre
`await db.commit()` (jamais dans la boucle de qualification, qui reste
avant le commit) — `_qualify_truck_stop` se contente de RETOURNER le
payload de l'événement à publier (ou `None`), jamais de le publier
lui-même, pour que le principe « publier après le commit de la
transaction qui a produit l'événement » (voir `app.shared.events`) soit
respecté même si un futur appelant de `_qualify_truck_stop` committe à un
autre moment que la fonction actuelle."""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.errors import AppError
from app.location.algorithms import (
    TRUCK_STOP_RADIUS_METERS_DEFAULT,
    TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT,
    detect_truck_stop_in_progress,
    detect_truck_stops,
    is_position_plausible,
    match_truck_stop_to_locations,
)
from app.location.models import (
    GpsDevice,
    GpsDeviceAssignment,
    GpsIngestCredential,
    TraccarConnection,
    TrackingSettings,
    TruckPositionPing,
    TruckStopComment,
    TruckStopEvent,
    TruckStopReconciliation,
    TruckTrackingLocation,
)
from app.location.permissions import (
    GPS_DEVICE_MANAGE,
    GPS_DEVICE_READ,
    TRACCAR_CONNECTION_MANAGE,
    TRACKING_LOCATION_MANAGE,
    TRACKING_LOCATION_READ,
    TRACKING_SETTINGS_MANAGE,
)
from app.location.schemas import (
    CreateGpsDeviceRequest,
    CreateTrackingLocationRequest,
    CreateTruckStopCommentRequest,
    GpsDeviceResponse,
    IngestTruckPositionRequest,
    ResolveTruckStopReconciliationRequest,
    TraccarConnectionRequest,
    TraccarConnectionResponse,
    TraccarDeviceListItem,
    TrackingLocationResponse,
    TrackingSettingsRequest,
    TrackingSettingsResponse,
    TruckCurrentPositionResponse,
    TruckPositionPingResponse,
    TruckStopCommentResponse,
    TruckStopEventResponse,
    TruckStopReconciliationResponse,
    UpdateGpsDeviceRequest,
    UpdateTrackingLocationRequest,
    UpdateTruckStopCommentRequest,
    VesselCurrentPositionResponse,
)
from app.modules.zylo_liquid.models import Truck
from app.modules.zylo_liquid.permissions import TRUCK_READ
from app.modules.zylo_tanker.models import Vessel
from app.modules.zylo_tanker.permissions import VESSEL_READ
from app.rbac.service import user_has_permission
from app.shared.events import publish
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta


async def _check_org_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)


async def _check_org_scope_any(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, permission_codes: list[str]) -> None:
    """Généralisation Zylo Tanker (2026-09-16) — passe si l'utilisateur a
    AU MOINS une des permissions listées, utilisé pour les fonctions
    partagées camion/navire (ex. réglages de tracking) où exiger une
    permission spécifique à un type de véhicule bloquerait à tort
    l'autre."""
    for code in permission_codes:
        if await user_has_permission(db, actor_user_id, organization_id, code):
            return
    raise AppError(code="permission_denied", message=f"Permission manquante : {' ou '.join(permission_codes)}.", status_code=403)


_TRUCK_STOP_LOOKBACK_HOURS = 48.0


async def _ensure_gps_device_identifier_available(db: AsyncSession, organization_id: uuid.UUID, device_identifier: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(GpsDevice).where(GpsDevice.organizationId == organization_id, GpsDevice.deviceIdentifier == device_identifier)
    if exclude_id is not None:
        stmt = stmt.where(GpsDevice.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise AppError(
            code="gps_device_identifier_already_used",
            message=f"Un boîtier GPS avec l'identifiant '{device_identifier}' existe déjà pour cette organisation.",
            status_code=409,
        )


async def _open_gps_device_assignment(db: AsyncSession, gps_device_id: uuid.UUID, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None) -> None:
    """Ouvre une nouvelle période d'association dans l'historique — jamais
    appelé sans avoir d'abord fermé toute période active existante pour ce
    boîtier (voir `unassign_gps_device`), sous peine de deux lignes actives
    simultanées pour le même boîtier. Généralisation Zylo Tanker
    (2026-09-16) : `truck_id` XOR `vessel_id`, jamais les deux.

    `assignedAt` fixé explicitement en Python (UTC naïf, même convention
    que tout le reste du fichier — voir `_close_active_gps_device_assignment`
    ci-dessous) plutôt que de laisser le `server_default=func.now()` du
    modèle s'appliquer : ce dernier hérite du fuseau de session Postgres,
    qui n'est UTC nulle part de façon garantie (poste local en UTC-4,
    CI en UTC) — un écart de plusieurs heures entre `assignedAt` et les
    `recordedAt` (toujours UTC naïf côté Python) faussait silencieusement
    le filtrage par fenêtre d'affectation (`_list_positions_for_period`,
    `run_truck_stop_detection`), en fonction du fuseau du serveur qui
    exécute le test — bug trouvé en comparant un run CI (échec) à un run
    local (vert) sur le même commit."""
    db.add(GpsDeviceAssignment(
        gpsDeviceId=gps_device_id, truckId=truck_id, vesselId=vessel_id,
        assignedAt=datetime.now(timezone.utc).replace(tzinfo=None),
    ))


async def _close_active_gps_device_assignment(db: AsyncSession, gps_device_id: uuid.UUID) -> None:
    result = await db.execute(
        select(GpsDeviceAssignment).where(GpsDeviceAssignment.gpsDeviceId == gps_device_id, GpsDeviceAssignment.unassignedAt.is_(None))
    )
    active = result.scalar_one_or_none()
    if active is not None:
        active.unassignedAt = datetime.now(timezone.utc).replace(tzinfo=None)


async def create_gps_device(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateGpsDeviceRequest) -> GpsDeviceResponse:
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_MANAGE)
    if data.truckId is not None and data.vesselId is not None:
        raise AppError(code="gps_device_truck_or_vessel_only", message="Un boîtier ne peut être assigné qu'à un camion OU un navire, jamais les deux.", status_code=422)
    if data.truckId is not None:
        truck = await db.get(Truck, data.truckId)
        if truck is None or truck.organizationId != organization_id:
            raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    if data.vesselId is not None:
        vessel = await db.get(Vessel, data.vesselId)
        if vessel is None or vessel.organizationId != organization_id:
            raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
    await _ensure_gps_device_identifier_available(db, organization_id, data.deviceIdentifier)
    instance = GpsDevice(organizationId=organization_id, truckId=data.truckId, vesselId=data.vesselId, deviceIdentifier=data.deviceIdentifier, label=data.label)
    db.add(instance)
    await db.flush()
    if data.truckId is not None:
        await _open_gps_device_assignment(db, instance.id, truck_id=data.truckId)
    elif data.vesselId is not None:
        await _open_gps_device_assignment(db, instance.id, vessel_id=data.vesselId)
    await db.commit()
    await db.refresh(instance)
    return GpsDeviceResponse.model_validate(instance)


async def update_gps_device(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, gps_device_id: uuid.UUID, data: UpdateGpsDeviceRequest) -> GpsDeviceResponse:
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_MANAGE)
    device = await db.get(GpsDevice, gps_device_id)
    if device is None or device.organizationId != organization_id:
        raise AppError(code="gps_device_not_found", message="Boîtier GPS introuvable.", status_code=404)
    updates = data.model_dump(exclude_unset=True)
    if updates.get("truckId") is not None and updates.get("vesselId") is not None:
        raise AppError(code="gps_device_truck_or_vessel_only", message="Un boîtier ne peut être assigné qu'à un camion OU un navire, jamais les deux.", status_code=422)
    if updates.get("truckId") is not None:
        truck = await db.get(Truck, updates["truckId"])
        if truck is None or truck.organizationId != organization_id:
            raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
        existing_result = await db.execute(
            select(GpsDeviceAssignment).where(GpsDeviceAssignment.truckId == updates["truckId"], GpsDeviceAssignment.unassignedAt.is_(None), GpsDeviceAssignment.gpsDeviceId != device.id)
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AppError(code="truck_already_has_device", message="Ce camion a déjà un boîtier GPS actif.", status_code=409)
        if updates["truckId"] != device.truckId:
            await _close_active_gps_device_assignment(db, device.id)
            await _open_gps_device_assignment(db, device.id, truck_id=updates["truckId"])
            # Bascule exclusive camion/navire (généralisation Zylo Tanker) —
            # une éventuelle affectation navire précédente sur ce boîtier
            # n'a plus de sens dès qu'il repasse camion.
            updates["vesselId"] = None
    # Généralisation Zylo Tanker (2026-09-16) — symétrique du bloc truckId
    # ci-dessus, jamais exécuté (donc jamais de changement de comportement)
    # pour une requête qui ne renseigne que truckId.
    if updates.get("vesselId") is not None:
        vessel = await db.get(Vessel, updates["vesselId"])
        if vessel is None or vessel.organizationId != organization_id:
            raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
        existing_vessel_result = await db.execute(
            select(GpsDeviceAssignment).where(GpsDeviceAssignment.vesselId == updates["vesselId"], GpsDeviceAssignment.unassignedAt.is_(None), GpsDeviceAssignment.gpsDeviceId != device.id)
        )
        if existing_vessel_result.scalar_one_or_none() is not None:
            raise AppError(code="vessel_already_has_device", message="Ce navire a déjà un boîtier GPS actif.", status_code=409)
        if updates["vesselId"] != device.vesselId:
            await _close_active_gps_device_assignment(db, device.id)
            await _open_gps_device_assignment(db, device.id, vessel_id=updates["vesselId"])
            updates["truckId"] = None
    for field, value in updates.items():
        setattr(device, field, value)
    await db.commit()
    await db.refresh(device)
    return GpsDeviceResponse.model_validate(device)


async def unassign_gps_device(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, gps_device_id: uuid.UUID) -> GpsDeviceResponse:
    """Dissociation explicite d'un boîtier de son camion/navire (scénario 2)
    — la confirmation « êtes-vous sûr » reste une responsabilité du
    frontend, cet appel exécute la dissociation dès qu'il est reçu. Ferme
    la période d'association active dans l'historique ; les positions/
    arrêts déjà enregistrés restent attribués au véhicule précédent pour
    toujours."""
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_MANAGE)
    device = await db.get(GpsDevice, gps_device_id)
    if device is None or device.organizationId != organization_id:
        raise AppError(code="gps_device_not_found", message="Boîtier GPS introuvable.", status_code=404)
    if device.truckId is not None or device.vesselId is not None:
        await _close_active_gps_device_assignment(db, device.id)
        device.truckId = None
        device.vesselId = None
    await db.commit()
    await db.refresh(device)
    return GpsDeviceResponse.model_validate(device)


async def list_gps_devices(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None,
) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_READ)
    stmt = select(GpsDevice).where(GpsDevice.organizationId == organization_id)
    if truck_id is not None:
        stmt = stmt.where(GpsDevice.truckId == truck_id)
    if vessel_id is not None:
        stmt = stmt.where(GpsDevice.vesselId == vessel_id)
    stmt = stmt.order_by(GpsDevice.deviceIdentifier)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[GpsDeviceResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def get_or_create_gps_ingest_credential(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> str:
    """Retourne le secret d'ingestion de l'organisation (le génère au
    premier appel) — affiché une seule fois à l'administrateur pour
    configurer le renvoi (forwarding) Traccar, jamais reloggé ensuite."""
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_MANAGE)
    result = await db.execute(select(GpsIngestCredential).where(GpsIngestCredential.organizationId == organization_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        credential = GpsIngestCredential(organizationId=organization_id, secretToken=secrets.token_urlsafe(32))
        db.add(credential)
        await db.commit()
        await db.refresh(credential)
    return credential.secretToken


async def regenerate_gps_ingest_credential(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> str:
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_MANAGE)
    result = await db.execute(select(GpsIngestCredential).where(GpsIngestCredential.organizationId == organization_id))
    credential = result.scalar_one_or_none()
    new_token = secrets.token_urlsafe(32)
    if credential is None:
        credential = GpsIngestCredential(organizationId=organization_id, secretToken=new_token)
        db.add(credential)
    else:
        credential.secretToken = new_token
    await db.commit()
    return new_token


async def _get_current_gps_device_for_owner(db: AsyncSession, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None) -> GpsDevice | None:
    """Un seul boîtier actif par camion/navire à la fois dans ce lot (v1) —
    pas de reconstitution d'historique à travers plusieurs boîtiers
    successifs. Généralisation Zylo Tanker (2026-09-16) de
    `_get_current_gps_device_for_truck` : `truck_id` XOR `vessel_id`."""
    if truck_id is not None:
        result = await db.execute(select(GpsDevice).where(GpsDevice.truckId == truck_id, GpsDevice.active == True))  # noqa: E712
    else:
        result = await db.execute(select(GpsDevice).where(GpsDevice.vesselId == vessel_id, GpsDevice.active == True))  # noqa: E712
    return result.scalar_one_or_none()


# Throttle de `run_truck_stop_detection` (2026-09-14, revue d'architecture) —
# sans lui, la fonction relit et rescanne jusqu'à 48h d'historique à CHAQUE
# position ingérée (pas d'état incrémental), un coût qui grandit en
# O(camions × pings²) et saturerait la base bien avant d'avoir une grande
# flotte (estimation : 20-100 camions selon la fréquence d'émission). Pas
# une solution finale (un état incrémental persisté serait mieux), mais un
# garde-fou simple et sûr : la fonction est idempotente et fait toujours un
# recalcul complet quand elle tourne, donc sauter des appels rapprochés ne
# perd jamais rien, juste retarde la détection de quelques secondes.
# Lu depuis l'environnement (pas une constante en dur) pour que la suite de
# tests puisse le ramener à 0 (voir conftest.py) — sinon des dizaines
# d'ingestions synthétiques envoyées en quelques millisecondes réelles ne
# déclencheraient plus qu'un seul calcul, avant que l'« arrêt » simulé ait
# eu le temps de s'accumuler.
_STOP_DETECTION_THROTTLE_SECONDS = float(os.environ.get("TRUCK_STOP_DETECTION_THROTTLE_SECONDS", "30"))
_last_stop_detection_run: dict[uuid.UUID, datetime] = {}


async def run_truck_stop_detection(db: AsyncSession, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None) -> list[TruckStopEvent]:
    """Exécute l'algorithme de détection d'arrêt (`detect_truck_stops`,
    jamais réimplémenté) sur les positions récentes du camion OU du navire
    (généralisation Zylo Tanker, 2026-09-16 : `truck_id` XOR `vessel_id`,
    positionnel `truck_id` conservé pour compatibilité avec les appelants
    existants), et persiste les arrêts non encore connus (idempotent via
    déduplication sur startAt) — même pattern que
    `run_delivery_detection_for_tank`.

    Bornage par fenêtre d'affectation (2026-09-13, correction) — même
    principe que `list_truck_positions` : chaque position n'est prise en
    compte QUE dans la période où son boîtier était réellement affecté à
    CE véhicule. Avant cette correction, la fonction regardait toutes les
    positions du boîtier *actuel* du véhicule sur 48h sans regarder qui
    l'avait porté pendant cette période — un arrêt pouvait donc être
    attribué à un véhicule alors que le boîtier était, au même instant,
    affecté à un autre véhicule (ou à aucun), après une réaffectation en
    cours de route (scénario 2)."""
    if (truck_id is None) == (vessel_id is None):
        raise ValueError("run_truck_stop_detection requiert exactement un de truck_id/vessel_id")
    owner_id = truck_id if truck_id is not None else vessel_id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_run = _last_stop_detection_run.get(owner_id)
    if last_run is not None and (now - last_run).total_seconds() < _STOP_DETECTION_THROTTLE_SECONDS:
        return []
    _last_stop_detection_run[owner_id] = now
    since = now - timedelta(hours=_TRUCK_STOP_LOOKBACK_HOURS)
    # `now` ne sert qu'à sélectionner les lignes d'affectation pertinentes
    # (une affectation ne peut pas commencer dans le futur) — jamais à
    # plafonner les positions elles-mêmes : une affectation encore ouverte
    # (`unassignedAt` nul) n'a AUCUNE borne haute ici, contrairement à
    # `list_truck_positions` qui reçoit un `until` explicite de l'appelant.
    # Plafonner au relogie serveur exclurait à tort toute position dont
    # l'horloge (ou l'injection de test) est même de quelques secondes en
    # avance sur ce process.
    assignments = await _get_truck_gps_assignments_for_period(db, since, now, truck_id=truck_id, vessel_id=vessel_id)
    if not assignments:
        return []
    all_positions: list[tuple] = []
    for assignment in assignments:
        window_start = max(since, assignment.assignedAt)
        query = select(TruckPositionPing.recordedAt, TruckPositionPing.latitude, TruckPositionPing.longitude).where(
            TruckPositionPing.gpsDeviceId == assignment.gpsDeviceId,
            TruckPositionPing.recordedAt >= window_start,
        )
        if assignment.unassignedAt is not None:
            if window_start > assignment.unassignedAt:
                continue
            query = query.where(TruckPositionPing.recordedAt <= assignment.unassignedAt)
        positions_result = await db.execute(query)
        all_positions.extend((recordedAt, float(lat), float(lon)) for recordedAt, lat, lon in positions_result.all())
    all_positions.sort(key=lambda p: p[0])
    positions = all_positions
    if len(positions) < 2:
        return []
    events = detect_truck_stops(positions, TRUCK_STOP_RADIUS_METERS_DEFAULT, TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT)
    if not events:
        return []

    owner_filter = TruckStopEvent.truckId == truck_id if truck_id is not None else TruckStopEvent.vesselId == vessel_id
    existing_result = await db.execute(select(TruckStopEvent.startAt).where(owner_filter))
    existing_start_times = {row[0] for row in existing_result.all()}

    created = []
    for event in events:
        if event["startTime"] in existing_start_times:
            continue
        instance = TruckStopEvent(
            truckId=truck_id, vesselId=vessel_id, latitude=event["latitude"], longitude=event["longitude"],
            startAt=event["startTime"], endAt=event["endTime"],
        )
        db.add(instance)
        created.append(instance)
    if created:
        await db.flush()
        owner = await db.get(Truck, truck_id) if truck_id is not None else await db.get(Vessel, vessel_id)
        pending_events: list[dict] = []
        for instance in created:
            # Qualification automatique (lieu connu / réconciliation /
            # événement d'arrêt non qualifié) — scénarios 5/6, best-effort
            # comme le reste de la détection dérivée : une erreur ici ne
            # doit jamais faire échouer la détection d'arrêt elle-même,
            # mais reste journalisée (jamais avalée en silence).
            try:
                event_payload = await _qualify_truck_stop(db, owner.organizationId, instance)
                if event_payload is not None:
                    pending_events.append(event_payload)
            except Exception:
                logger.exception("échec de la qualification automatique de l'arrêt %s (best-effort)", instance.id)
        await db.commit()
        for instance in created:
            await db.refresh(instance)
        # Publié seulement ici, après le commit ci-dessus — jamais dans la
        # boucle de qualification (voir la docstring de ce fichier et
        # celle de `app.shared.events`).
        for event_payload in pending_events:
            await publish("TruckStopUnqualified", **event_payload)
    return created


async def ingest_truck_position(db: AsyncSession, organization_id: uuid.UUID, secret_token: str, data: IngestTruckPositionRequest) -> TruckPositionPingResponse:
    """Point d'entrée du webhook Traccar — jamais un utilisateur connecté
    (pas de JWT ici), authentifié par le secret d'ingestion de
    l'organisation (`GpsIngestCredential`). `organization_id` vient du
    header X-Organization-Id (exigé par `require_module_active` sur tout
    le routeur zylo_liquid) — le secret doit correspondre à CETTE
    organisation précisément, pas n'importe laquelle."""
    credential_result = await db.execute(
        select(GpsIngestCredential).where(GpsIngestCredential.organizationId == organization_id, GpsIngestCredential.secretToken == secret_token)
    )
    credential = credential_result.scalar_one_or_none()
    if credential is None:
        raise AppError(code="invalid_ingest_secret", message="Secret d'ingestion invalide.", status_code=401)

    device_result = await db.execute(
        select(GpsDevice).where(GpsDevice.organizationId == credential.organizationId, GpsDevice.deviceIdentifier == data.deviceIdentifier)
    )
    device = device_result.scalar_one_or_none()
    if device is None:
        raise AppError(code="gps_device_not_found", message=f"Boîtier GPS inconnu : {data.deviceIdentifier}.", status_code=404)

    recorded_at = data.recordedAt.replace(tzinfo=None) if data.recordedAt.tzinfo else data.recordedAt

    # Filtre de plausibilité (2026-09-13, incident réel) — rejette un point
    # dont la vitesse implicite depuis la dernière position connue de CE
    # boîtier est physiquement impossible pour un camion-citerne (voir
    # `is_position_plausible`). Comparaison sur `recordedAt`, jamais
    # `receivedAt` : deux points reçus dans le même lot après une coupure
    # réseau peuvent avoir un `recordedAt` très différent l'un de l'autre.
    last_ping_result = await db.execute(
        select(TruckPositionPing.recordedAt, TruckPositionPing.latitude, TruckPositionPing.longitude)
        .where(TruckPositionPing.gpsDeviceId == device.id)
        .order_by(TruckPositionPing.recordedAt.desc())
        .limit(1)
    )
    last_ping_row = last_ping_result.first()
    if last_ping_row is not None and not is_position_plausible(
        last_ping_row.recordedAt, float(last_ping_row.latitude), float(last_ping_row.longitude),
        recorded_at, data.latitude, data.longitude,
    ):
        logger.warning(
            "position rejetée (vitesse implicite irréaliste) : boîtier=%s recordedAt=%s lat=%s lon=%s",
            data.deviceIdentifier, recorded_at, data.latitude, data.longitude,
        )
        raise AppError(code="implausible_position", message="Position rejetée : vitesse implicite irréaliste depuis la dernière position connue.", status_code=422)

    ping = TruckPositionPing(
        gpsDeviceId=device.id,
        # recordedAt est une colonne TIMESTAMP WITHOUT TIME ZONE — un
        # boîtier/passerelle envoie souvent un horodatage avec fuseau
        # explicite (ex. Traccar : "+00:00"), à dépouiller avant insertion
        # (même bug que sur les endpoints de lecture positions/arrêts,
        # trouvé et corrigé plus tôt dans cette même mission).
        recordedAt=recorded_at,
        latitude=data.latitude, longitude=data.longitude,
        channel=data.channel, accuracyMeters=data.accuracyMeters, speedKmh=data.speedKmh,
        rawPayload=data.model_dump(mode="json"),
    )
    db.add(ping)
    await db.commit()
    await db.refresh(ping)

    if device.truckId is not None:
        try:
            await run_truck_stop_detection(db, truck_id=device.truckId)
        except Exception:
            # Best-effort : une erreur de calcul dérivé ne doit jamais faire
            # échouer l'ingestion elle-même (même discipline que le
            # rapprochement automatique de livraison) — mais désormais
            # journalisée (2026-09-13) : une erreur silencieuse ici avait
            # caché plusieurs heures d'arrêts manquants en conditions
            # réelles, sans aucune trace exploitable pour diagnostiquer.
            logger.exception("échec du calcul des arrêts (best-effort) pour le camion %s", device.truckId)
    elif device.vesselId is not None:
        # Généralisation Zylo Tanker (2026-09-16) — même discipline
        # best-effort que le camion ci-dessus, le webhook d'ingestion reste
        # unique quel que soit le type de véhicule propriétaire du boîtier.
        try:
            await run_truck_stop_detection(db, vessel_id=device.vesselId)
        except Exception:
            logger.exception("échec du calcul des arrêts (best-effort) pour le navire %s", device.vesselId)

    return TruckPositionPingResponse.model_validate(ping)


async def _resolve_owner_current_position(db: AsyncSession, device: GpsDevice | None, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None):
    """Cœur partagé de `list_truck_current_positions`/
    `list_vessel_current_positions` (généralisation Zylo Tanker,
    2026-09-16) — jamais dupliqué. Retourne
    (latitude, longitude, recordedAt, channel, in_progress) où `in_progress`
    est le payload d'arrêt en cours (voir `detect_truck_stop_in_progress`)
    ou `None`, tous `None` si aucune position exploitable."""
    if device is None:
        return None, None, None, None, None
    last_ping_result = await db.execute(
        select(TruckPositionPing).where(TruckPositionPing.gpsDeviceId == device.id).order_by(TruckPositionPing.recordedAt.desc()).limit(1)
    )
    last_ping = last_ping_result.scalar_one_or_none()
    if last_ping is None:
        return None, None, None, None, None

    # Bornée à l'affectation en cours de CE véhicule (2026-09-13,
    # correction) — jamais 48h de positions du boîtier sans savoir s'il
    # était bien sur ce véhicule pendant tout cet intervalle.
    owner_filter = GpsDeviceAssignment.truckId == truck_id if truck_id is not None else GpsDeviceAssignment.vesselId == vessel_id
    current_assignment_result = await db.execute(
        select(GpsDeviceAssignment.assignedAt)
        .where(owner_filter, GpsDeviceAssignment.gpsDeviceId == device.id, GpsDeviceAssignment.unassignedAt.is_(None))
        .order_by(GpsDeviceAssignment.assignedAt.desc())
        .limit(1)
    )
    current_assignment_start = current_assignment_result.scalar_one_or_none()
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=_TRUCK_STOP_LOOKBACK_HOURS)
    if current_assignment_start is not None:
        since = max(since, current_assignment_start)
    recent_result = await db.execute(
        select(TruckPositionPing.recordedAt, TruckPositionPing.latitude, TruckPositionPing.longitude)
        .where(TruckPositionPing.gpsDeviceId == device.id, TruckPositionPing.recordedAt >= since)
        .order_by(TruckPositionPing.recordedAt)
    )
    recent_positions = [(recordedAt, float(lat), float(lon)) for recordedAt, lat, lon in recent_result.all()]
    in_progress = detect_truck_stop_in_progress(recent_positions, TRUCK_STOP_RADIUS_METERS_DEFAULT, TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT) if len(recent_positions) >= 2 else None
    return float(last_ping.latitude), float(last_ping.longitude), last_ping.recordedAt, last_ping.channel, in_progress


async def list_truck_current_positions(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> list[TruckCurrentPositionResponse]:
    """Dernière position connue de chaque camion de l'organisation, pour la
    carte — même esprit que `get_station_current_state` (une seule requête
    agrégée, jamais une donnée dupliquée côté client)."""
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_READ)
    trucks_result = await db.execute(select(Truck.id).where(Truck.organizationId == organization_id))
    truck_ids = [row[0] for row in trucks_result.all()]
    if not truck_ids:
        return []

    responses: list[TruckCurrentPositionResponse] = []
    for truck_id in truck_ids:
        device = await _get_current_gps_device_for_owner(db, truck_id=truck_id)
        latitude, longitude, recorded_at, channel, in_progress = await _resolve_owner_current_position(db, device, truck_id=truck_id)
        current_stop = None
        if in_progress is not None:
            current_stop = TruckStopEventResponse(
                id=uuid.uuid4(), truckId=truck_id, latitude=in_progress["latitude"], longitude=in_progress["longitude"],
                startAt=in_progress["startTime"], endAt=None,
            )
        responses.append(TruckCurrentPositionResponse(
            truckId=truck_id, latitude=latitude, longitude=longitude,
            recordedAt=recorded_at, channel=channel, currentStop=current_stop,
        ))
    return responses


async def list_vessel_current_positions(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> list[VesselCurrentPositionResponse]:
    """Généralisation Zylo Tanker (2026-09-16) de `list_truck_current_positions`
    — même cœur partagé (`_resolve_owner_current_position`), jamais dupliqué."""
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_READ)
    vessels_result = await db.execute(select(Vessel.id).where(Vessel.organizationId == organization_id))
    vessel_ids = [row[0] for row in vessels_result.all()]
    if not vessel_ids:
        return []

    responses: list[VesselCurrentPositionResponse] = []
    for vessel_id in vessel_ids:
        device = await _get_current_gps_device_for_owner(db, vessel_id=vessel_id)
        latitude, longitude, recorded_at, channel, in_progress = await _resolve_owner_current_position(db, device, vessel_id=vessel_id)
        current_stop = None
        if in_progress is not None:
            current_stop = TruckStopEventResponse(
                id=uuid.uuid4(), vesselId=vessel_id, latitude=in_progress["latitude"], longitude=in_progress["longitude"],
                startAt=in_progress["startTime"], endAt=None,
            )
        responses.append(VesselCurrentPositionResponse(
            vesselId=vessel_id, latitude=latitude, longitude=longitude,
            recordedAt=recorded_at, channel=channel, currentStop=current_stop,
        ))
    return responses


async def _get_truck_gps_assignments_for_period(
    db: AsyncSession, since: datetime, until: datetime, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None,
) -> list[GpsDeviceAssignment]:
    """Périodes d'association boîtier<->camion (ou boîtier<->navire,
    généralisation Zylo Tanker 2026-09-16) qui chevauchent la fenêtre
    demandée — jamais seulement le boîtier actuel (`GpsDevice.truckId`/
    `vesselId`), qui aurait déjà changé après une réaffectation (scénario 2 :
    l'historique du camion A reste consultable même après que son boîtier
    soit passé au camion B)."""
    owner_filter = GpsDeviceAssignment.truckId == truck_id if truck_id is not None else GpsDeviceAssignment.vesselId == vessel_id
    result = await db.execute(
        select(GpsDeviceAssignment).where(
            owner_filter,
            GpsDeviceAssignment.assignedAt <= until,
            or_(GpsDeviceAssignment.unassignedAt.is_(None), GpsDeviceAssignment.unassignedAt >= since),
        )
    )
    return list(result.scalars().all())


async def _list_positions_for_period(db: AsyncSession, since: datetime, until: datetime, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None) -> list[TruckPositionPingResponse]:
    """Cœur partagé de `list_truck_positions`/`list_vessel_positions`
    (généralisation Zylo Tanker, 2026-09-16) — jamais dupliqué."""
    assignments = await _get_truck_gps_assignments_for_period(db, since, until, truck_id=truck_id, vessel_id=vessel_id)
    if not assignments:
        return []
    # Chaque position n'est retenue que dans les bornes de SA propre période
    # d'association — jamais seulement la fenêtre demandée — pour ne
    # jamais faire fuiter les positions d'un autre véhicule ayant porté le
    # même boîtier avant/après cette période précise.
    all_positions: list[TruckPositionPing] = []
    for assignment in assignments:
        window_start = max(since, assignment.assignedAt)
        window_end = min(until, assignment.unassignedAt) if assignment.unassignedAt else until
        if window_start > window_end:
            continue
        result = await db.execute(
            select(TruckPositionPing).where(
                TruckPositionPing.gpsDeviceId == assignment.gpsDeviceId,
                TruckPositionPing.recordedAt >= window_start,
                TruckPositionPing.recordedAt <= window_end,
            )
        )
        all_positions.extend(result.scalars().all())
    all_positions.sort(key=lambda p: p.recordedAt)
    return [TruckPositionPingResponse.model_validate(r) for r in all_positions]


async def list_truck_positions(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, truck_id: uuid.UUID, since: datetime, until: datetime) -> list[TruckPositionPingResponse]:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_READ)
    truck = await db.get(Truck, truck_id)
    if truck is None or truck.organizationId != organization_id:
        raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    return await _list_positions_for_period(db, since, until, truck_id=truck_id)


async def list_vessel_positions(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, vessel_id: uuid.UUID, since: datetime, until: datetime) -> list[TruckPositionPingResponse]:
    """Généralisation Zylo Tanker (2026-09-16) de `list_truck_positions` —
    réutilise `TruckPositionPingResponse` tel quel (déjà agnostique du type
    de véhicule, voir `app/location/models.py::TruckPositionPing`)."""
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_READ)
    vessel = await db.get(Vessel, vessel_id)
    if vessel is None or vessel.organizationId != organization_id:
        raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
    return await _list_positions_for_period(db, since, until, vessel_id=vessel_id)


async def _list_stops_for_period(db: AsyncSession, since: datetime, until: datetime, *, truck_id: uuid.UUID | None = None, vessel_id: uuid.UUID | None = None) -> list[TruckStopEventResponse]:
    """Cœur partagé de `list_truck_stops`/`list_vessel_stops`
    (généralisation Zylo Tanker, 2026-09-16) — jamais dupliqué."""
    owner_filter = TruckStopEvent.truckId == truck_id if truck_id is not None else TruckStopEvent.vesselId == vessel_id
    result = await db.execute(
        select(TruckStopEvent)
        .where(owner_filter, TruckStopEvent.startAt >= since, TruckStopEvent.startAt <= until)
        .order_by(TruckStopEvent.startAt)
    )
    return [TruckStopEventResponse.model_validate(r) for r in result.scalars().all()]


async def list_truck_stops(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, truck_id: uuid.UUID, since: datetime, until: datetime) -> list[TruckStopEventResponse]:
    await _check_org_scope(db, organization_id, actor_user_id, TRUCK_READ)
    truck = await db.get(Truck, truck_id)
    if truck is None or truck.organizationId != organization_id:
        raise AppError(code="truck_not_found", message="Camion introuvable.", status_code=404)
    return await _list_stops_for_period(db, since, until, truck_id=truck_id)


async def list_vessel_stops(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, vessel_id: uuid.UUID, since: datetime, until: datetime) -> list[TruckStopEventResponse]:
    """Généralisation Zylo Tanker (2026-09-16) de `list_truck_stops`."""
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_READ)
    vessel = await db.get(Vessel, vessel_id)
    if vessel is None or vessel.organizationId != organization_id:
        raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
    return await _list_stops_for_period(db, since, until, vessel_id=vessel_id)


# ================================================================
# Tracking GPS des camions-citernes — étape 2 (flux métier, 2026-09).
# Traccar garde son rôle strict de passerelle protocole (voir plan) : les
# seuls appels sortants vers son API sont `POST /api/session` (login) et
# `GET /api/devices` (liste des boîtiers), jamais ses géozones ni ses
# rapports trajets/arrêts propres.
# ================================================================


async def get_traccar_connection(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> TraccarConnectionResponse | None:
    await _check_org_scope(db, organization_id, actor_user_id, TRACCAR_CONNECTION_MANAGE)
    result = await db.execute(select(TraccarConnection).where(TraccarConnection.organizationId == organization_id))
    connection = result.scalar_one_or_none()
    return TraccarConnectionResponse.model_validate(connection) if connection else None


async def _test_traccar_login(base_url: str, username: str, password: str) -> None:
    """Tente réellement une connexion à Traccar (`POST /api/session`) —
    jamais une simple validation de forme de l'URL. Lève `AppError` si ça
    échoue, avec le détail réel renvoyé par Traccar (ou l'erreur réseau),
    jamais un message générique qui masquerait la vraie cause (mauvaise
    adresse, mauvais port, identifiants invalides...)."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
            login_response = await client.post("/api/session", data={"email": username, "password": password})
            login_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AppError(
            code="traccar_connection_failed",
            message=f"Traccar a refusé la connexion (HTTP {exc.response.status_code}) — vérifiez l'adresse du serveur et les identifiants.",
            status_code=502,
        ) from exc
    except httpx.HTTPError as exc:
        raise AppError(code="traccar_connection_failed", message=f"Impossible de joindre Traccar à cette adresse : {exc}", status_code=502) from exc


async def set_traccar_connection(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: TraccarConnectionRequest) -> TraccarConnectionResponse:
    """Teste réellement la connexion à Traccar avant toute sauvegarde
    (scénario 1, décision du commanditaire 2026-09-13) — une configuration
    qui ne fonctionne pas n'est jamais enregistrée, l'ancienne (si elle
    existait et fonctionnait) reste en place."""
    await _check_org_scope(db, organization_id, actor_user_id, TRACCAR_CONNECTION_MANAGE)
    await _test_traccar_login(data.baseUrl, data.username, data.password)

    result = await db.execute(select(TraccarConnection).where(TraccarConnection.organizationId == organization_id))
    connection = result.scalar_one_or_none()
    if connection is None:
        connection = TraccarConnection(organizationId=organization_id, baseUrl=data.baseUrl, username=data.username, password=data.password)
        db.add(connection)
    else:
        connection.baseUrl = data.baseUrl
        connection.username = data.username
        connection.password = data.password
    await db.commit()
    await db.refresh(connection)
    return TraccarConnectionResponse.model_validate(connection)


async def list_traccar_devices(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> list[TraccarDeviceListItem]:
    """Liste des boîtiers déjà enregistrés dans Traccar (scénario 1) —
    jamais de saisie manuelle d'identifiant côté Zylo Liquid. Croise avec
    `GpsDevice`/`Truck` pour indiquer l'association actuelle, si elle
    existe."""
    await _check_org_scope(db, organization_id, actor_user_id, GPS_DEVICE_READ)
    result = await db.execute(select(TraccarConnection).where(TraccarConnection.organizationId == organization_id))
    connection = result.scalar_one_or_none()
    if connection is None:
        raise AppError(
            code="traccar_connection_not_configured",
            message="Connexion à Traccar non configurée pour cette organisation.",
            status_code=422,
        )

    try:
        async with httpx.AsyncClient(base_url=connection.baseUrl, timeout=10) as client:
            login_response = await client.post("/api/session", data={"email": connection.username, "password": connection.password})
            login_response.raise_for_status()
            devices_response = await client.get("/api/devices")
            devices_response.raise_for_status()
            traccar_devices = devices_response.json()
    except httpx.HTTPError as exc:
        raise AppError(code="traccar_connection_failed", message=f"Impossible de joindre Traccar : {exc}", status_code=502) from exc

    known_result = await db.execute(select(GpsDevice, Truck.plateNumber).outerjoin(Truck, Truck.id == GpsDevice.truckId).where(GpsDevice.organizationId == organization_id))
    known_by_identifier = {device.deviceIdentifier: (device, plate) for device, plate in known_result.all()}

    items: list[TraccarDeviceListItem] = []
    for raw in traccar_devices:
        unique_id = raw.get("uniqueId")
        if not unique_id:
            continue
        known = known_by_identifier.get(unique_id)
        items.append(TraccarDeviceListItem(
            deviceIdentifier=unique_id,
            name=raw.get("name"),
            online=raw.get("status") == "online",
            lastPositionAt=raw.get("lastUpdate"),
            truckId=known[0].truckId if known else None,
            truckPlateNumber=known[1] if known else None,
        ))
    return items


async def _ensure_tracking_location_movable(db: AsyncSession, location: TruckTrackingLocation) -> None:
    """Règle validée avec le commanditaire (scénario 3) : un lieu jamais
    visité (aucun `TruckStopEvent` ne le référence) peut être déplacé
    librement ; un lieu déjà visité ne peut plus être déplacé, pour ne
    jamais fausser rétroactivement un historique déjà qualifié."""
    result = await db.execute(select(func.count()).select_from(TruckStopEvent).where(TruckStopEvent.locationId == location.id))
    if (result.scalar() or 0) > 0:
        raise AppError(
            code="tracking_location_has_history",
            message="Ce lieu a déjà été visité — sa position ne peut plus être déplacée. Créez un nouveau lieu si l'emplacement a changé.",
            status_code=409,
        )


async def create_tracking_location(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateTrackingLocationRequest) -> TrackingLocationResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_MANAGE)
    instance = TruckTrackingLocation(
        organizationId=organization_id, name=data.name, type=data.type,
        latitude=data.latitude, longitude=data.longitude, radiusMeters=data.radiusMeters,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return TrackingLocationResponse.model_validate(instance)


async def update_tracking_location(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, location_id: uuid.UUID, data: UpdateTrackingLocationRequest) -> TrackingLocationResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_MANAGE)
    location = await db.get(TruckTrackingLocation, location_id)
    if location is None or location.organizationId != organization_id:
        raise AppError(code="tracking_location_not_found", message="Lieu introuvable.", status_code=404)
    updates = data.model_dump(exclude_unset=True)
    if ("latitude" in updates or "longitude" in updates) and (
        (updates.get("latitude") is not None and float(updates["latitude"]) != float(location.latitude))
        or (updates.get("longitude") is not None and float(updates["longitude"]) != float(location.longitude))
    ):
        await _ensure_tracking_location_movable(db, location)
    for field, value in updates.items():
        setattr(location, field, value)
    await db.commit()
    await db.refresh(location)
    return TrackingLocationResponse.model_validate(location)


async def delete_tracking_location(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, location_id: uuid.UUID) -> TrackingLocationResponse:
    """Jamais de suppression physique si le lieu a déjà été visité —
    passage en `status='deleted'`, reste visible (grisé) dans l'historique
    des trajets qui le référencent (scénario 3)."""
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_MANAGE)
    location = await db.get(TruckTrackingLocation, location_id)
    if location is None or location.organizationId != organization_id:
        raise AppError(code="tracking_location_not_found", message="Lieu introuvable.", status_code=404)
    result = await db.execute(select(func.count()).select_from(TruckStopEvent).where(TruckStopEvent.locationId == location.id))
    has_history = (result.scalar() or 0) > 0
    if has_history:
        location.status = "deleted"
    else:
        await db.delete(location)
    await db.commit()
    if has_history:
        await db.refresh(location)
        return TrackingLocationResponse.model_validate(location)
    return TrackingLocationResponse(id=location_id, organizationId=organization_id, name="", type="libre", latitude=0, longitude=0, radiusMeters=0, status="deleted")


async def list_tracking_locations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, include_deleted: bool = False) -> list[TrackingLocationResponse]:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_READ)
    stmt = select(TruckTrackingLocation).where(TruckTrackingLocation.organizationId == organization_id)
    if not include_deleted:
        stmt = stmt.where(TruckTrackingLocation.status == "active")
    result = await db.execute(stmt.order_by(TruckTrackingLocation.name))
    return [TrackingLocationResponse.model_validate(r) for r in result.scalars().all()]


async def get_tracking_settings(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> TrackingSettingsResponse:
    # Réglages partagés camion/navire (généralisation Zylo Tanker,
    # 2026-09-16) — TRUCK_READ OU VESSEL_READ suffit, jamais les deux
    # exigés : un opérateur navire sans TRUCK_READ doit pouvoir lire les
    # réglages de tracking de son organisation comme un opérateur camion.
    await _check_org_scope_any(db, organization_id, actor_user_id, [TRUCK_READ, VESSEL_READ])
    result = await db.execute(select(TrackingSettings).where(TrackingSettings.organizationId == organization_id))
    settings_row = result.scalar_one_or_none()
    if settings_row is None:
        return TrackingSettingsResponse(organizationId=organization_id, stopStabilizationMinutes=None, stopRadiusMeters=None, liveViewThrottleMs=None)
    return TrackingSettingsResponse.model_validate(settings_row)


async def update_tracking_settings(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: TrackingSettingsRequest) -> TrackingSettingsResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_SETTINGS_MANAGE)
    result = await db.execute(select(TrackingSettings).where(TrackingSettings.organizationId == organization_id))
    settings_row = result.scalar_one_or_none()
    updates = data.model_dump(exclude_unset=True)
    if settings_row is None:
        settings_row = TrackingSettings(organizationId=organization_id, **updates)
        db.add(settings_row)
    else:
        for field, value in updates.items():
            setattr(settings_row, field, value)
    await db.commit()
    await db.refresh(settings_row)
    return TrackingSettingsResponse.model_validate(settings_row)


async def _qualify_truck_stop(db: AsyncSession, organization_id: uuid.UUID, stop: TruckStopEvent) -> dict | None:
    """Reconnaissance automatique de lieu + qualification d'un arrêt non
    qualifié (scénarios 5/6) — appelé juste après la persistance d'un
    nouvel arrêt confirmé, jamais rétroactivement sur les arrêts déjà
    qualifiés. Retourne le payload de l'événement `TruckStopUnqualified` à
    publier par l'appelant (après son propre commit), ou `None` si l'arrêt
    a été reconnu/mis en réconciliation (aucun événement dans ces deux cas)."""
    locations_result = await db.execute(
        select(TruckTrackingLocation.id, TruckTrackingLocation.latitude, TruckTrackingLocation.longitude, TruckTrackingLocation.radiusMeters)
        .where(TruckTrackingLocation.organizationId == organization_id, TruckTrackingLocation.status == "active")
    )
    locations = [(loc_id, float(lat), float(lon), float(radius)) for loc_id, lat, lon, radius in locations_result.all()]
    match = match_truck_stop_to_locations(float(stop.latitude), float(stop.longitude), locations) if locations else {"status": "unmatched"}

    if match["status"] == "matched":
        stop.locationId = match["locationId"]
        stop.reconciliationStatus = "none"
        return None

    if match["status"] == "ambiguous":
        stop.reconciliationStatus = "pending"
        db.add(TruckStopReconciliation(stopEventId=stop.id, candidateLocationIds=[str(c) for c in match["candidateIds"]]))
        return None

    # unmatched : arrêt hors de tout lieu connu -> événement de domaine
    # (scénario 6), seuil déjà appliqué en amont par la détection d'arrêt
    # elle-même (confirmation = seuil unique, configurable via
    # TrackingSettings, plus de deuxième délai d'alerte séparé). Phase 5 :
    # ne publie plus directement — retourne le payload, publié par
    # l'appelant après son commit (voir la docstring de ce fichier et
    # celle de `app.shared.events`).
    return {
        "truck_id": stop.truckId,
        "vessel_id": stop.vesselId,
        "alert_type": "truck_stop_unqualified",
        "triggered_at": stop.startAt,
        "source_type": "TruckStopEvent",
        "source_id": stop.id,
    }


def _stop_read_permission(stop: TruckStopEvent) -> str:
    """Généralisation Zylo Tanker (2026-09-16) — la permission de lecture
    requise pour un arrêt dépend du type de véhicule propriétaire, jamais
    figée à TRUCK_READ (qui bloquerait à tort un opérateur navire)."""
    return TRUCK_READ if stop.truckId is not None else VESSEL_READ


async def create_truck_stop_comment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, stop_id: uuid.UUID, data: CreateTruckStopCommentRequest) -> TruckStopCommentResponse:
    # Ordre changé (généralisation Zylo Tanker, 2026-09-16) : l'arrêt doit
    # être résolu AVANT de savoir quelle permission vérifier (TRUCK_READ ou
    # VESSEL_READ selon son propriétaire) — un stop_id inconnu répond donc
    # désormais 404 avant tout contrôle de permission, jamais l'inverse.
    stop = await _get_truck_stop_or_404(db, organization_id, stop_id)
    await _check_org_scope(db, organization_id, actor_user_id, _stop_read_permission(stop))
    instance = TruckStopComment(stopEventId=stop.id, authorUserId=actor_user_id, body=data.body)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return TruckStopCommentResponse.model_validate(instance)


async def update_truck_stop_comment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, comment_id: uuid.UUID, data: UpdateTruckStopCommentRequest) -> TruckStopCommentResponse:
    comment = await db.get(TruckStopComment, comment_id)
    if comment is None:
        raise AppError(code="truck_stop_comment_not_found", message="Commentaire introuvable.", status_code=404)
    stop = await _get_truck_stop_or_404(db, organization_id, comment.stopEventId)
    await _check_org_scope(db, organization_id, actor_user_id, _stop_read_permission(stop))
    comment.body = data.body
    await db.commit()
    await db.refresh(comment)
    return TruckStopCommentResponse.model_validate(comment)


async def delete_truck_stop_comment(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, comment_id: uuid.UUID) -> None:
    comment = await db.get(TruckStopComment, comment_id)
    if comment is None:
        raise AppError(code="truck_stop_comment_not_found", message="Commentaire introuvable.", status_code=404)
    stop = await _get_truck_stop_or_404(db, organization_id, comment.stopEventId)
    await _check_org_scope(db, organization_id, actor_user_id, _stop_read_permission(stop))
    await db.delete(comment)
    await db.commit()


async def list_truck_stop_comments(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, stop_id: uuid.UUID) -> list[TruckStopCommentResponse]:
    stop = await _get_truck_stop_or_404(db, organization_id, stop_id)
    await _check_org_scope(db, organization_id, actor_user_id, _stop_read_permission(stop))
    result = await db.execute(select(TruckStopComment).where(TruckStopComment.stopEventId == stop_id).order_by(TruckStopComment.createdAt))
    return [TruckStopCommentResponse.model_validate(r) for r in result.scalars().all()]


async def _get_truck_stop_or_404(db: AsyncSession, organization_id: uuid.UUID, stop_id: uuid.UUID) -> TruckStopEvent:
    """Généralisation Zylo Tanker (2026-09-16) — résout le propriétaire de
    l'arrêt (camion OU navire, jamais les deux, voir la contrainte CHECK
    sur `TruckStopEvent`) et vérifie sa portée d'organisation quel que soit
    le type de véhicule."""
    stop = await db.get(TruckStopEvent, stop_id)
    if stop is None:
        raise AppError(code="truck_stop_not_found", message="Arrêt introuvable.", status_code=404)
    if stop.truckId is not None:
        truck = await db.get(Truck, stop.truckId)
        if truck is None or truck.organizationId != organization_id:
            raise AppError(code="truck_stop_not_found", message="Arrêt introuvable.", status_code=404)
    else:
        vessel = await db.get(Vessel, stop.vesselId)
        if vessel is None or vessel.organizationId != organization_id:
            raise AppError(code="truck_stop_not_found", message="Arrêt introuvable.", status_code=404)
    return stop


async def list_truck_stop_reconciliations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, status: str | None = "pending") -> list[TruckStopReconciliationResponse]:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_READ)
    stmt = (
        select(TruckStopReconciliation)
        .join(TruckStopEvent, TruckStopEvent.id == TruckStopReconciliation.stopEventId)
        .join(Truck, Truck.id == TruckStopEvent.truckId)
        .where(Truck.organizationId == organization_id)
    )
    if status is not None:
        stmt = stmt.where(TruckStopReconciliation.status == status)
    result = await db.execute(stmt.order_by(TruckStopReconciliation.createdAt))
    return [TruckStopReconciliationResponse.model_validate(r) for r in result.scalars().all()]


async def list_vessel_stop_reconciliations(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, status: str | None = "pending") -> list[TruckStopReconciliationResponse]:
    """Généralisation Zylo Tanker (2026-09-16) de
    `list_truck_stop_reconciliations` — même requête, jointure sur
    `Vessel` au lieu de `Truck` (seule différence : la table qui porte la
    portée d'organisation)."""
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_READ)
    stmt = (
        select(TruckStopReconciliation)
        .join(TruckStopEvent, TruckStopEvent.id == TruckStopReconciliation.stopEventId)
        .join(Vessel, Vessel.id == TruckStopEvent.vesselId)
        .where(Vessel.organizationId == organization_id)
    )
    if status is not None:
        stmt = stmt.where(TruckStopReconciliation.status == status)
    result = await db.execute(stmt.order_by(TruckStopReconciliation.createdAt))
    return [TruckStopReconciliationResponse.model_validate(r) for r in result.scalars().all()]


async def resolve_truck_stop_reconciliation(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, reconciliation_id: uuid.UUID, data: ResolveTruckStopReconciliationRequest,
) -> TruckStopReconciliationResponse:
    await _check_org_scope(db, organization_id, actor_user_id, TRACKING_LOCATION_MANAGE)
    reconciliation = await db.get(TruckStopReconciliation, reconciliation_id)
    if reconciliation is None:
        raise AppError(code="truck_stop_reconciliation_not_found", message="Réconciliation introuvable.", status_code=404)
    stop = await _get_truck_stop_or_404(db, organization_id, reconciliation.stopEventId)
    if data.locationId is not None and str(data.locationId) not in reconciliation.candidateLocationIds:
        raise AppError(code="invalid_reconciliation_choice", message="Ce lieu ne fait pas partie des candidats proposés.", status_code=422)
    reconciliation.status = "resolved"
    reconciliation.resolvedLocationId = data.locationId
    reconciliation.resolvedByUserId = actor_user_id
    reconciliation.resolvedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    stop.locationId = data.locationId
    stop.reconciliationStatus = "resolved"
    await db.commit()
    await db.refresh(reconciliation)
    return TruckStopReconciliationResponse.model_validate(reconciliation)
