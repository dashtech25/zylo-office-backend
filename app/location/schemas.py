"""Schémas du module Location (tracking GPS des camions-citernes) —
extraits de `app/modules/zylo_liquid/schemas.py` (2026-09-15, Phase 2 de
la migration monolithe modulaire, voir ARCHITECTURE.md). Contenu
inchangé, seul l'emplacement du code Python bouge."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ================================================================
# Tracking GPS des camions-citernes (mission « tracking », étape 1)
# ================================================================


class CreateGpsDeviceRequest(BaseModel):
    truckId: uuid.UUID | None = Field(default=None, description="Camion à associer dès la création — laisser vide pour enregistrer un boîtier en stock, non encore posé sur un véhicule.")
    deviceIdentifier: str = Field(min_length=1, max_length=50, description="Identifiant unique du boîtier tel que configuré côté Traccar (ex. 'uniqueId') — doit être unique par organisation.")
    label: str | None = Field(default=None, max_length=150, description="Libellé libre affiché à l'utilisateur, distinct de deviceIdentifier.")


class UpdateGpsDeviceRequest(BaseModel):
    truckId: uuid.UUID | None = Field(default=None, description="Réaffecter à un autre camion ferme automatiquement la période d'association active précédente et en ouvre une nouvelle.")
    label: str | None = Field(default=None, max_length=150)
    active: bool | None = None


class GpsDeviceResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    truckId: uuid.UUID | None
    deviceIdentifier: str
    label: str | None
    active: bool

    model_config = {"from_attributes": True}


# ================================================================
# Tracking GPS des camions-citernes — étape 2 (flux métier, 2026-09)
# ================================================================


class TraccarConnectionRequest(BaseModel):
    baseUrl: str = Field(min_length=1, max_length=255, description="URL de base du serveur Traccar (ex. https://traccar.exemple.com) — testée par un login réel avant sauvegarde.")
    username: str = Field(min_length=1, max_length=255, description="Identifiant de connexion Traccar (compte technique, pas un compte Zylo Office).")
    password: str = Field(min_length=1, max_length=255)


class TraccarConnectionResponse(BaseModel):
    """Le mot de passe est renvoyé en clair (décision explicite du
    commanditaire, 2026-09-13) — le formulaire de configuration doit
    toujours pré-remplir le mot de passe actuel, jamais un champ vide,
    avec bascule affiché/masqué côté client."""

    id: uuid.UUID
    organizationId: uuid.UUID
    baseUrl: str
    username: str
    password: str

    model_config = {"from_attributes": True}


class TraccarDeviceListItem(BaseModel):
    """Un boîtier tel que listé depuis l'API Traccar (scénario 1) —
    jamais persisté tel quel, uniquement une vue pour l'association."""

    deviceIdentifier: str
    name: str | None
    online: bool
    lastPositionAt: datetime | None
    truckId: uuid.UUID | None
    truckPlateNumber: str | None


class CreateTrackingLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: str = Field(default="libre", pattern="^(port|entrepot|depot_fournisseur|libre)$", description="Catégorie du lieu — 'port', 'entrepot', 'depot_fournisseur' ou 'libre' (valeur par défaut).")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radiusMeters: float = Field(default=150.0, gt=0, le=5000, description="Rayon (mètres) autour du point dans lequel un arrêt de camion est considéré comme se produisant à ce lieu.")


class UpdateTrackingLocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: str | None = Field(default=None, pattern="^(port|entrepot|depot_fournisseur|libre)$")
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Déplacer le lieu (latitude/longitude) est refusé (409) dès qu'un arrêt l'a déjà référencé.")
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radiusMeters: float | None = Field(default=None, gt=0, le=5000)


class TrackingLocationResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    type: str
    latitude: float
    longitude: float
    radiusMeters: float
    status: str

    model_config = {"from_attributes": True}


class TruckStopReconciliationResponse(BaseModel):
    """Créée automatiquement quand un arrêt détecté correspond de façon
    également plausible à plusieurs lieux de tracking connus (ambiguïté) —
    à trancher manuellement via `resolve_truck_stop_reconciliation`."""

    id: uuid.UUID
    stopEventId: uuid.UUID
    candidateLocationIds: list[uuid.UUID] = Field(description="Lieux candidats parmi lesquels choisir — le seul ensemble de valeurs acceptées pour resolvedLocationId.")
    status: str = Field(description="'pending' (en attente d'arbitrage) ou 'resolved' (tranchée).")
    resolvedLocationId: uuid.UUID | None = Field(description="Lieu retenu après arbitrage — null si 'aucun des deux' a été choisi ou si non encore résolue.")
    resolvedByUserId: uuid.UUID | None
    resolvedAt: datetime | None

    model_config = {"from_attributes": True}


class ResolveTruckStopReconciliationRequest(BaseModel):
    """`locationId` absent/None = « aucun des deux », l'arrêt reste non
    qualifié en connaissance de cause (scénario 5)."""

    locationId: uuid.UUID | None = None


class CreateTruckStopCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class UpdateTruckStopCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class TruckStopCommentResponse(BaseModel):
    id: uuid.UUID
    stopEventId: uuid.UUID
    authorUserId: uuid.UUID
    body: str
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


class TrackingSettingsRequest(BaseModel):
    stopStabilizationMinutes: float | None = Field(default=None, gt=0, le=180, description="Durée minimale d'immobilité (minutes) avant qu'un arrêt soit considéré confirmé par la détection.")
    stopRadiusMeters: float | None = Field(default=None, gt=0, le=5000, description="Rayon (mètres) en dessous duquel des positions successives sont considérées comme un même arrêt.")
    liveViewThrottleMs: int | None = Field(default=None, ge=0, le=60000, description="Fréquence minimale (millisecondes) de rafraîchissement de la vue carte en direct, côté client.")


class TrackingSettingsResponse(BaseModel):
    organizationId: uuid.UUID
    stopStabilizationMinutes: float | None = Field(description="null si non personnalisé — le backend applique alors sa valeur par défaut interne.")
    stopRadiusMeters: float | None = Field(description="null si non personnalisé — le backend applique alors sa valeur par défaut interne.")
    liveViewThrottleMs: int | None

    model_config = {"from_attributes": True}


class IngestTruckPositionRequest(BaseModel):
    """Contrat d'ingestion contrôlé par Zylo Liquid — `deviceIdentifier`
    doit correspondre à celui enregistré sur un `GpsDevice` (le
    rapprochement exact avec le champ envoyé par Traccar, deviceId ou
    uniqueId selon la configuration, est un réglage fait à la passerelle,
    pas ici)."""

    deviceIdentifier: str = Field(min_length=1, max_length=50, description="Doit correspondre à un GpsDevice déjà enregistré (404 sinon) — le rapprochement avec le champ envoyé par Traccar (deviceId/uniqueId) est un réglage fait côté passerelle, pas ici.")
    recordedAt: datetime = Field(description="Horodatage de mesure du GPS (pas de réception par ce backend) — comparé à la dernière position connue pour rejeter une vitesse implicite irréaliste (422).")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    channel: str | None = None
    accuracyMeters: float | None = Field(default=None, ge=0)
    speedKmh: float | None = Field(default=None, ge=0)


class TruckPositionPingResponse(BaseModel):
    id: uuid.UUID
    gpsDeviceId: uuid.UUID
    recordedAt: datetime
    receivedAt: datetime
    latitude: float
    longitude: float
    channel: str | None
    accuracyMeters: float | None
    speedKmh: float | None

    model_config = {"from_attributes": True}


class TruckStopEventResponse(BaseModel):
    id: uuid.UUID
    truckId: uuid.UUID
    latitude: float
    longitude: float
    startAt: datetime
    endAt: datetime | None = Field(description="null tant que l'arrêt est en cours (camion toujours immobile) — rempli une fois le camion reparti.")
    locationId: uuid.UUID | None = Field(default=None, description="Lieu de tracking reconnu automatiquement — null si non rattaché (hors de tout lieu connu, ou en attente de réconciliation manuelle).")
    reconciliationStatus: str = Field(default="none", description="'none' (pas d'ambiguïté), 'pending' (ambigu, en attente d'arbitrage via /truck-stop-reconciliations) ou 'resolved' (ambiguïté tranchée manuellement).")

    model_config = {"from_attributes": True}


class TruckCurrentPositionResponse(BaseModel):
    """Une entrée existe pour chaque camion de l'organisation, même sans
    boîtier GPS assigné ou sans position jamais reçue : les champs de
    position valent alors tous null plutôt que d'omettre le camion."""

    truckId: uuid.UUID
    latitude: float | None = Field(description="null si le camion n'a pas de boîtier GPS assigné ou n'a jamais émis de position.")
    longitude: float | None = Field(description="null si le camion n'a pas de boîtier GPS assigné ou n'a jamais émis de position.")
    recordedAt: datetime | None = Field(description="Horodatage de la dernière position connue — null dans les mêmes cas que latitude/longitude.")
    channel: str | None
    currentStop: TruckStopEventResponse | None = Field(default=None, description="Arrêt en cours si le camion est actuellement immobile depuis le seuil de stabilisation configuré — null s'il est en mouvement ou sans position.")
