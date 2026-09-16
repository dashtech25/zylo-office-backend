"""Routes du module Location (tracking GPS des camions-citernes ET,
généralisation Zylo Tanker 2026-09-16, des navires) — extraites de
`app/modules/zylo_liquid/router.py` (2026-09-15, Phase 2). Ce routeur est
désormais monté DEUX FOIS dans `app/api/v1/router.py` : sous `/zylo-liquid`
(comportement historique, inchangé) et sous `/zylo-tanker` (nouveau) — le
déplacement/la duplication de montage ne doit jamais casser une URL déjà
consommée par le frontend zylo_liquid.

Faille de sécurité corrigée ici (2026-09-16, voir le plan de mission) :
avant cette généralisation, `router = APIRouter()` n'avait AUCUNE garde
`require_module_active` au niveau du routeur — contrairement à
`zylo_liquid/router.py`, qui pose `Depends(require_module_active("zylo_liquid"))`
une seule fois pour tout le routeur. Les routes de ce fichier
(`/gps-devices`, `/trucks/current-positions`...) étaient donc accessibles
même si l'organisation n'avait JAMAIS activé zylo_liquid. Avec deux modules
consommateurs, une garde unique de routeur n'est de toute façon plus
possible : chaque route reçoit maintenant une garde explicite —
`require_module_active("zylo_liquid")` pour les routes camion,
`require_module_active("zylo_tanker")` pour les routes navire, et
`require_module_active_any("zylo_liquid", "zylo_tanker")`
(`app/modules_registry/service.py`) pour les routes réellement partagées
(boîtiers GPS, connexion Traccar, lieux nommés, réglages de tracking,
secret d'ingestion) qui n'ont pas de deuxième URL dédiée — accessibles dès
que l'UN des deux modules est actif. Seul le webhook d'ingestion
(`POST /gps/ingest`) reste sans garde de module : Traccar ne sait pas
distinguer camion/navire et n'a pas à le savoir, protégé uniquement par le
secret d'ingestion de l'organisation."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.database import AsyncSessionLocal, get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.location import service
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
from app.modules_registry.service import require_module_active, require_module_active_any
from app.rbac.service import get_current_organization_id
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page

router = APIRouter()

_ZYLO_LIQUID = Depends(require_module_active("zylo_liquid"))
_ZYLO_TANKER = Depends(require_module_active("zylo_tanker"))
_SHARED = Depends(require_module_active_any("zylo_liquid", "zylo_tanker"))


@router.post("/gps-devices", response_model=GpsDeviceResponse, status_code=201, summary="Enregistrer un nouveau boîtier GPS", dependencies=[_SHARED])
async def create_gps_device(
    data: CreateGpsDeviceRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> GpsDeviceResponse:
    """Crée le boîtier et, si `truckId` (ou `vesselId`, généralisation Zylo
    Tanker) est fourni, ouvre immédiatement une période d'association dans
    l'historique boîtier<->véhicule. Route partagée entre `/zylo-liquid` et
    `/zylo-tanker` (accessible dès que l'un des deux modules est actif)."""
    return await service.create_gps_device(db, organization_id, current_user.id, data)


@router.get("/gps-devices", response_model=Page[GpsDeviceResponse], summary="Lister les boîtiers GPS de l'organisation", dependencies=[_SHARED])
async def list_gps_devices(
    pagination: PaginationParams = Depends(),
    truckId: uuid.UUID | None = None,
    vesselId: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_gps_devices(db, organization_id, current_user.id, pagination, truckId, vesselId)


@router.patch("/gps-devices/{gps_device_id}", response_model=GpsDeviceResponse, summary="Modifier un boîtier GPS", dependencies=[_SHARED])
async def update_gps_device(
    gps_device_id: uuid.UUID,
    data: UpdateGpsDeviceRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> GpsDeviceResponse:
    """Réaffecter `truckId`/`vesselId` à un nouveau véhicule ferme
    automatiquement la période d'association active précédente et en ouvre
    une nouvelle — refusé (409) si le véhicule cible a déjà un autre
    boîtier actif, ou (422) si les deux champs sont renseignés à la fois."""
    return await service.update_gps_device(db, organization_id, current_user.id, gps_device_id, data)


@router.post("/gps-devices/{gps_device_id}/unassign", response_model=GpsDeviceResponse, summary="Dissocier un boîtier GPS de son véhicule", dependencies=[_SHARED])
async def unassign_gps_device(
    gps_device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> GpsDeviceResponse:
    """Ferme la période d'association active dans l'historique — les
    positions/arrêts déjà enregistrés restent attribués au véhicule
    précédent pour toujours. Aucune étape de confirmation ici : la
    dissociation est exécutée dès réception de l'appel."""
    return await service.unassign_gps_device(db, organization_id, current_user.id, gps_device_id)


@router.get("/traccar-connection", response_model=TraccarConnectionResponse | None, summary="Lire la configuration de connexion à Traccar", dependencies=[_SHARED])
async def get_traccar_connection(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TraccarConnectionResponse | None:
    """Retourne `null` si aucune connexion Traccar n'a encore été
    configurée pour cette organisation. Le mot de passe est renvoyé en
    clair (voir `TraccarConnectionResponse`)."""
    return await service.get_traccar_connection(db, organization_id, current_user.id)


@router.post("/traccar-connection", response_model=TraccarConnectionResponse, summary="Configurer (ou remplacer) la connexion à Traccar", dependencies=[_SHARED])
async def set_traccar_connection(
    data: TraccarConnectionRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TraccarConnectionResponse:
    """Teste réellement la connexion (login Traccar) avant toute
    sauvegarde : une configuration qui échoue n'est jamais enregistrée,
    l'ancienne configuration (si elle existait) reste en place — répond
    502 en cas d'échec de connexion."""
    return await service.set_traccar_connection(db, organization_id, current_user.id, data)


@router.get("/gps-devices/from-traccar", response_model=list[TraccarDeviceListItem], summary="Lister les boîtiers disponibles côté Traccar", dependencies=[_SHARED])
async def list_traccar_devices(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TraccarDeviceListItem]:
    """Interroge en direct l'API Traccar configurée (`/api/devices`) —
    jamais de saisie manuelle d'identifiant côté Zylo Liquid. Chaque
    boîtier renvoyé indique s'il est déjà associé à un camion connu.
    Nécessite qu'une connexion Traccar ait été configurée au préalable
    (422 sinon)."""
    return await service.list_traccar_devices(db, organization_id, current_user.id)


@router.post("/tracking-locations", response_model=TrackingLocationResponse, status_code=201, summary="Créer un lieu de tracking nommé", dependencies=[_SHARED])
async def create_tracking_location(
    data: CreateTrackingLocationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLocationResponse:
    """Un lieu connu (port, entrepôt, dépôt fournisseur ou lieu libre) que
    la détection d'arrêt tente ensuite de reconnaître automatiquement —
    voir `resolve_truck_stop_reconciliation` pour le cas ambigu. Partagé
    entre camions et navires (le type 'port' sert aussi bien à qualifier
    l'arrêt d'un camion que celui d'un navire)."""
    return await service.create_tracking_location(db, organization_id, current_user.id, data)


@router.get("/tracking-locations", response_model=list[TrackingLocationResponse], summary="Lister les lieux de tracking", dependencies=[_SHARED])
async def list_tracking_locations(
    includeDeleted: bool = False,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TrackingLocationResponse]:
    return await service.list_tracking_locations(db, organization_id, current_user.id, includeDeleted)


@router.patch("/tracking-locations/{location_id}", response_model=TrackingLocationResponse, summary="Modifier un lieu de tracking", dependencies=[_SHARED])
async def update_tracking_location(
    location_id: uuid.UUID,
    data: UpdateTrackingLocationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLocationResponse:
    """Déplacer un lieu (latitude/longitude) est refusé (409) dès qu'un
    arrêt l'a déjà référencé — pour ne jamais fausser rétroactivement un
    historique déjà qualifié. Créez un nouveau lieu si l'emplacement réel a
    changé."""
    return await service.update_tracking_location(db, organization_id, current_user.id, location_id, data)


@router.delete("/tracking-locations/{location_id}", response_model=TrackingLocationResponse, summary="Supprimer un lieu de tracking", dependencies=[_SHARED])
async def delete_tracking_location(
    location_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLocationResponse:
    """Suppression physique uniquement si le lieu n'a jamais été visité ;
    sinon passage en `status='deleted'` (reste visible, grisé, dans
    l'historique des arrêts qui le référencent)."""
    return await service.delete_tracking_location(db, organization_id, current_user.id, location_id)


@router.get("/truck-stop-reconciliations", response_model=list[TruckStopReconciliationResponse], summary="Lister les arrêts camion en attente de réconciliation manuelle", dependencies=[_ZYLO_LIQUID])
async def list_truck_stop_reconciliations(
    status: str | None = "pending",
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopReconciliationResponse]:
    """Une réconciliation existe quand un arrêt détecté correspond à
    plusieurs lieux connus à la fois de façon également plausible
    (candidats dans `candidateLocationIds`) — voir
    `resolve_truck_stop_reconciliation` pour trancher."""
    return await service.list_truck_stop_reconciliations(db, organization_id, current_user.id, status)


@router.post("/truck-stop-reconciliations/{reconciliation_id}/resolve", response_model=TruckStopReconciliationResponse, summary="Trancher manuellement un arrêt camion ambigu entre plusieurs lieux candidats", dependencies=[_ZYLO_LIQUID])
async def resolve_truck_stop_reconciliation(
    reconciliation_id: uuid.UUID,
    data: ResolveTruckStopReconciliationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopReconciliationResponse:
    """`locationId` doit être l'un des candidats proposés (`candidateLocationIds`
    de la réconciliation), ou `null`/absent pour dire « aucun des deux » —
    l'arrêt reste alors non qualifié en connaissance de cause plutôt que de
    forcer un choix arbitraire."""
    return await service.resolve_truck_stop_reconciliation(db, organization_id, current_user.id, reconciliation_id, data)


@router.get("/vessel-stop-reconciliations", response_model=list[TruckStopReconciliationResponse], summary="Lister les arrêts navire en attente de réconciliation manuelle", dependencies=[_ZYLO_TANKER])
async def list_vessel_stop_reconciliations(
    status: str | None = "pending",
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopReconciliationResponse]:
    """Symétrique de `/truck-stop-reconciliations` (généralisation Zylo
    Tanker, 2026-09-16), pour les navires."""
    return await service.list_vessel_stop_reconciliations(db, organization_id, current_user.id, status)


@router.post("/vessel-stop-reconciliations/{reconciliation_id}/resolve", response_model=TruckStopReconciliationResponse, summary="Trancher manuellement un arrêt navire ambigu entre plusieurs lieux candidats", dependencies=[_ZYLO_TANKER])
async def resolve_vessel_stop_reconciliation(
    reconciliation_id: uuid.UUID,
    data: ResolveTruckStopReconciliationRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopReconciliationResponse:
    """Réutilise `service.resolve_truck_stop_reconciliation`, déjà
    agnostique du type de véhicule (résout l'arrêt via `_get_truck_stop_or_404`,
    généralisé) — jamais de logique dupliquée, seule la route/garde diffère."""
    return await service.resolve_truck_stop_reconciliation(db, organization_id, current_user.id, reconciliation_id, data)


@router.post("/truck-stops/{stop_id}/comments", response_model=TruckStopCommentResponse, status_code=201, summary="Ajouter un commentaire sur un arrêt de camion", dependencies=[_ZYLO_LIQUID])
async def create_truck_stop_comment(
    stop_id: uuid.UUID,
    data: CreateTruckStopCommentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopCommentResponse:
    return await service.create_truck_stop_comment(db, organization_id, current_user.id, stop_id, data)


@router.get("/truck-stops/{stop_id}/comments", response_model=list[TruckStopCommentResponse], summary="Lister les commentaires d'un arrêt de camion", dependencies=[_ZYLO_LIQUID])
async def list_truck_stop_comments(
    stop_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopCommentResponse]:
    return await service.list_truck_stop_comments(db, organization_id, current_user.id, stop_id)


@router.patch("/truck-stop-comments/{comment_id}", response_model=TruckStopCommentResponse, summary="Modifier un commentaire d'arrêt de camion", dependencies=[_ZYLO_LIQUID])
async def update_truck_stop_comment(
    comment_id: uuid.UUID,
    data: UpdateTruckStopCommentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopCommentResponse:
    return await service.update_truck_stop_comment(db, organization_id, current_user.id, comment_id, data)


@router.delete("/truck-stop-comments/{comment_id}", status_code=204, summary="Supprimer un commentaire d'arrêt de camion", dependencies=[_ZYLO_LIQUID])
async def delete_truck_stop_comment(
    comment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_truck_stop_comment(db, organization_id, current_user.id, comment_id)


@router.post("/vessel-stops/{stop_id}/comments", response_model=TruckStopCommentResponse, status_code=201, summary="Ajouter un commentaire sur un arrêt de navire", dependencies=[_ZYLO_TANKER])
async def create_vessel_stop_comment(
    stop_id: uuid.UUID,
    data: CreateTruckStopCommentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopCommentResponse:
    """Symétrique de `/truck-stops/{stop_id}/comments` — réutilise
    `service.create_truck_stop_comment`, déjà agnostique du type de
    véhicule (voir sa docstring)."""
    return await service.create_truck_stop_comment(db, organization_id, current_user.id, stop_id, data)


@router.get("/vessel-stops/{stop_id}/comments", response_model=list[TruckStopCommentResponse], summary="Lister les commentaires d'un arrêt de navire", dependencies=[_ZYLO_TANKER])
async def list_vessel_stop_comments(
    stop_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopCommentResponse]:
    return await service.list_truck_stop_comments(db, organization_id, current_user.id, stop_id)


@router.patch("/vessel-stop-comments/{comment_id}", response_model=TruckStopCommentResponse, summary="Modifier un commentaire d'arrêt de navire", dependencies=[_ZYLO_TANKER])
async def update_vessel_stop_comment(
    comment_id: uuid.UUID,
    data: UpdateTruckStopCommentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckStopCommentResponse:
    return await service.update_truck_stop_comment(db, organization_id, current_user.id, comment_id, data)


@router.delete("/vessel-stop-comments/{comment_id}", status_code=204, summary="Supprimer un commentaire d'arrêt de navire", dependencies=[_ZYLO_TANKER])
async def delete_vessel_stop_comment(
    comment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_truck_stop_comment(db, organization_id, current_user.id, comment_id)


@router.get("/tracking-settings", response_model=TrackingSettingsResponse, summary="Lire les réglages de tracking de l'organisation", dependencies=[_SHARED])
async def get_tracking_settings(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingSettingsResponse:
    """Un champ à `null` signifie qu'aucun réglage personnalisé n'a été
    défini pour cette organisation — le backend applique alors ses valeurs
    par défaut internes (non exposées ici). Partagé camion/navire."""
    return await service.get_tracking_settings(db, organization_id, current_user.id)


@router.patch("/tracking-settings", response_model=TrackingSettingsResponse, summary="Modifier les réglages de tracking de l'organisation", dependencies=[_SHARED])
async def update_tracking_settings(
    data: TrackingSettingsRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingSettingsResponse:
    return await service.update_tracking_settings(db, organization_id, current_user.id, data)


@router.get("/gps-ingest-credential", summary="Lire (ou générer au premier appel) le secret d'ingestion GPS", dependencies=[_SHARED])
async def get_gps_ingest_credential(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ce secret est celui à renseigner dans la configuration de renvoi
    (forwarding) Traccar vers `POST /gps/ingest` — il n'est jamais
    rejournalisé après sa création, seul ce endpoint permet de le
    reconsulter. Un seul secret par organisation, quel que soit le nombre
    de boîtiers camion/navire qui l'utilisent."""
    token = await service.get_or_create_gps_ingest_credential(db, organization_id, current_user.id)
    return {"secretToken": token}


@router.post("/gps-ingest-credential/regenerate", summary="Régénérer le secret d'ingestion GPS", dependencies=[_SHARED])
async def regenerate_gps_ingest_credential(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalide immédiatement l'ancien secret — toute passerelle encore
    configurée avec l'ancienne valeur cessera de pouvoir ingérer des
    positions tant qu'elle n'est pas mise à jour."""
    token = await service.regenerate_gps_ingest_credential(db, organization_id, current_user.id)
    return {"secretToken": token}


@router.post("/gps/ingest", response_model=TruckPositionPingResponse, status_code=201, summary="Webhook d'ingestion d'une position GPS (appelé par Traccar)")
async def ingest_truck_position(
    data: IngestTruckPositionRequest,
    x_gps_ingest_secret: str = Header(...),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TruckPositionPingResponse:
    """Webhook appelé par Traccar (passerelle protocole GPS) — jamais un
    utilisateur Zylo Office connecté, aucune dépendance `get_current_user`
    ici. Volontairement SANS garde `require_module_active` (ni zylo_liquid
    ni zylo_tanker ni la variante `_any`) : un seul webhook sert les deux
    types de boîtier, Traccar ne sait pas la différence et n'a pas à la
    savoir — protégé uniquement par le secret d'ingestion de l'organisation
    (`X-Gps-Ingest-Secret`), vérifié dans `service.ingest_truck_position`."""
    return await service.ingest_truck_position(db, organization_id, x_gps_ingest_secret, data)


@router.get("/trucks/current-positions", response_model=list[TruckCurrentPositionResponse], summary="Dernière position connue de chaque camion (pour la carte)", dependencies=[_ZYLO_LIQUID])
async def list_truck_current_positions(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckCurrentPositionResponse]:
    """Une entrée par camion de l'organisation, même sans aucun boîtier GPS
    assigné ou sans position jamais reçue : `latitude`/`longitude`/
    `recordedAt`/`channel` valent alors `null` plutôt que d'omettre le
    camion — le client n'a jamais besoin de croiser avec la liste des
    camions pour savoir qui n'est pas suivi. `currentStop` n'est rempli que
    si le camion est actuellement immobile depuis le seuil de
    stabilisation configuré (arrêt en cours, pas encore un
    `TruckStopEvent` persisté)."""
    return await service.list_truck_current_positions(db, organization_id, current_user.id)


@router.get("/vessels/current-positions", response_model=list[VesselCurrentPositionResponse], summary="Dernière position connue de chaque navire (pour la carte)", dependencies=[_ZYLO_TANKER])
async def list_vessel_current_positions(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[VesselCurrentPositionResponse]:
    """Symétrique de `/trucks/current-positions` (généralisation Zylo
    Tanker, 2026-09-16)."""
    return await service.list_vessel_current_positions(db, organization_id, current_user.id)


_LIVE_POSITIONS_POLL_SECONDS = 5.0


@router.get("/trucks/live-positions", summary="Flux SSE des positions courantes de tous les camions", dependencies=[_ZYLO_LIQUID])
async def stream_truck_live_positions(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
) -> StreamingResponse:
    """Flux SSE (Server-Sent Events) des positions courantes des camions
    (2026-09-14, revue d'architecture) — aucun push depuis Traccar/le pont
    (recherche : le mécanisme d'intégration documenté et fiable de Traccar
    est `forward.url`, pas son WebSocket `/api/socket`, pensé pour son
    propre client web). Le seul vrai trou identifié était en aval, entre
    ce backend et notre frontend, qui ne se rafraîchissait jamais tout
    seul. Réexécute simplement `list_truck_current_positions` (aucune
    nouvelle logique métier) toutes les `_LIVE_POSITIONS_POLL_SECONDS`, le
    temps que la connexion SSE reste ouverte — une session `AsyncSessionLocal`
    fraîche à chaque itération, jamais une session maintenue ouverte
    pendant tout le flux (elle serait inactive le reste du temps entre
    deux tours, exactement le bug de connexion Neon déjà rencontré une
    fois cette session). Pas de Redis/pub-sub : un seul process backend
    aujourd'hui, chaque connexion SSE interroge la base indépendamment —
    à revoir seulement si plusieurs instances backend tournent un jour en
    parallèle.

    Format SSE écrit à la main (StreamingResponse brut, 2026-09-14) —
    aussi bien le support SSE natif de FastAPI (`fastapi.sse`, bug de
    sérialisation constaté : `ServerSentEvent` non converti en texte) que
    `sse-starlette` (blocage constaté à la connexion avec les versions de
    Starlette installées ici) se sont révélés peu fiables ; le format SSE
    lui-même est trivial (`data: <json>\\n\\n`), écrire les quelques lignes
    à la main évite ces deux dépendances fragiles."""
    async def event_generator():
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    positions = await service.list_truck_current_positions(db, organization_id, current_user.id)
                payload = json.dumps([p.model_dump(mode="json") for p in positions])
                yield f"data: {payload}\n\n".encode()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("échec du flux de positions en direct (camion)")
            await asyncio.sleep(_LIVE_POSITIONS_POLL_SECONDS)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/vessels/live-positions", summary="Flux SSE des positions courantes de tous les navires", dependencies=[_ZYLO_TANKER])
async def stream_vessel_live_positions(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
) -> StreamingResponse:
    """Symétrique de `/trucks/live-positions` (généralisation Zylo Tanker,
    2026-09-16) — même mécanique (polling `AsyncSessionLocal` frais à
    chaque itération), jamais dupliquée en profondeur, seule la fonction
    de résolution des positions courantes diffère."""
    async def event_generator():
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    positions = await service.list_vessel_current_positions(db, organization_id, current_user.id)
                payload = json.dumps([p.model_dump(mode="json") for p in positions])
                yield f"data: {payload}\n\n".encode()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("échec du flux de positions en direct (navire)")
            await asyncio.sleep(_LIVE_POSITIONS_POLL_SECONDS)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/trucks/{truck_id}/positions", response_model=list[TruckPositionPingResponse], summary="Historique des positions GPS d'un camion", dependencies=[_ZYLO_LIQUID])
async def list_truck_positions(
    truck_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckPositionPingResponse]:
    """`since`/`until` par défaut : les dernières 24h. Chaque position
    n'est retournée que si elle a été enregistrée pendant une période où le
    boîtier GPS émetteur était réellement affecté à CE camion — jamais les
    positions d'un autre camion ayant porté le même boîtier avant/après une
    réaffectation."""
    # Les colonnes recordedAt/startAt sont TIMESTAMP WITHOUT TIME ZONE — un
    # since/until fourni par le client (souvent suffixé "Z", donc tz-aware
    # une fois parsé par Pydantic) doit être dépouillé de son fuseau avant
    # toute comparaison, sinon asyncpg refuse (offset-naive vs offset-aware).
    resolved_until = (until or datetime.now(timezone.utc)).replace(tzinfo=None)
    resolved_since = (since.replace(tzinfo=None) if since else resolved_until - timedelta(hours=24))
    return await service.list_truck_positions(db, organization_id, current_user.id, truck_id, resolved_since, resolved_until)


@router.get("/vessels/{vessel_id}/positions", response_model=list[TruckPositionPingResponse], summary="Historique des positions GPS d'un navire", dependencies=[_ZYLO_TANKER])
async def list_vessel_positions(
    vessel_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckPositionPingResponse]:
    """Symétrique de `/trucks/{truck_id}/positions` (généralisation Zylo
    Tanker, 2026-09-16)."""
    resolved_until = (until or datetime.now(timezone.utc)).replace(tzinfo=None)
    resolved_since = (since.replace(tzinfo=None) if since else resolved_until - timedelta(hours=24))
    return await service.list_vessel_positions(db, organization_id, current_user.id, vessel_id, resolved_since, resolved_until)


@router.get("/trucks/{truck_id}/stops", response_model=list[TruckStopEventResponse], summary="Historique des arrêts détectés d'un camion", dependencies=[_ZYLO_LIQUID])
async def list_truck_stops(
    truck_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopEventResponse]:
    """`since`/`until` par défaut : les dernières 24h. Un arrêt confirmé
    (`endAt` non nul) provient de la détection automatique
    (`detect_truck_stops`) ; `locationId`/`reconciliationStatus` indiquent
    si l'arrêt a été rattaché à un lieu connu, reste ambigu (`pending`, via
    `/truck-stop-reconciliations`) ou n'a matché aucun lieu (`none`)."""
    # Les colonnes recordedAt/startAt sont TIMESTAMP WITHOUT TIME ZONE — un
    # since/until fourni par le client (souvent suffixé "Z", donc tz-aware
    # une fois parsé par Pydantic) doit être dépouillé de son fuseau avant
    # toute comparaison, sinon asyncpg refuse (offset-naive vs offset-aware).
    resolved_until = (until or datetime.now(timezone.utc)).replace(tzinfo=None)
    resolved_since = (since.replace(tzinfo=None) if since else resolved_until - timedelta(hours=24))
    return await service.list_truck_stops(db, organization_id, current_user.id, truck_id, resolved_since, resolved_until)


@router.get("/vessels/{vessel_id}/stops", response_model=list[TruckStopEventResponse], summary="Historique des arrêts détectés d'un navire", dependencies=[_ZYLO_TANKER])
async def list_vessel_stops(
    vessel_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[TruckStopEventResponse]:
    """Symétrique de `/trucks/{truck_id}/stops` (généralisation Zylo
    Tanker, 2026-09-16) — même algorithme de détection d'arrêt
    (`detect_truck_stops`), même reconnaissance automatique de lieu connu,
    même file de réconciliation (`/vessel-stop-reconciliations`)."""
    resolved_until = (until or datetime.now(timezone.utc)).replace(tzinfo=None)
    resolved_since = (since.replace(tzinfo=None) if since else resolved_until - timedelta(hours=24))
    return await service.list_vessel_stops(db, organization_id, current_user.id, vessel_id, resolved_since, resolved_until)
