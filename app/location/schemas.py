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
    truckId: uuid.UUID | None = None
    deviceIdentifier: str = Field(min_length=1, max_length=50)
    label: str | None = Field(default=None, max_length=150)


class UpdateGpsDeviceRequest(BaseModel):
    truckId: uuid.UUID | None = None
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
    baseUrl: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
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
    type: str = Field(default="libre", pattern="^(port|entrepot|depot_fournisseur|libre)$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radiusMeters: float = Field(default=150.0, gt=0, le=5000)


class UpdateTrackingLocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: str | None = Field(default=None, pattern="^(port|entrepot|depot_fournisseur|libre)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
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
    id: uuid.UUID
    stopEventId: uuid.UUID
    candidateLocationIds: list[uuid.UUID]
    status: str
    resolvedLocationId: uuid.UUID | None
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
    stopStabilizationMinutes: float | None = Field(default=None, gt=0, le=180)
    stopRadiusMeters: float | None = Field(default=None, gt=0, le=5000)
    liveViewThrottleMs: int | None = Field(default=None, ge=0, le=60000)


class TrackingSettingsResponse(BaseModel):
    organizationId: uuid.UUID
    stopStabilizationMinutes: float | None
    stopRadiusMeters: float | None
    liveViewThrottleMs: int | None

    model_config = {"from_attributes": True}


class IngestTruckPositionRequest(BaseModel):
    """Contrat d'ingestion contrôlé par Zylo Liquid — `deviceIdentifier`
    doit correspondre à celui enregistré sur un `GpsDevice` (le
    rapprochement exact avec le champ envoyé par Traccar, deviceId ou
    uniqueId selon la configuration, est un réglage fait à la passerelle,
    pas ici)."""

    deviceIdentifier: str = Field(min_length=1, max_length=50)
    recordedAt: datetime
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
    endAt: datetime | None
    locationId: uuid.UUID | None = None
    reconciliationStatus: str = "none"

    model_config = {"from_attributes": True}


class TruckCurrentPositionResponse(BaseModel):
    truckId: uuid.UUID
    latitude: float | None
    longitude: float | None
    recordedAt: datetime | None
    channel: str | None
    currentStop: TruckStopEventResponse | None = None
