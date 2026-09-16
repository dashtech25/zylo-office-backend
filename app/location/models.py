"""Modèles du module Location (tracking GPS des camions-citernes) —
extraits de `app/modules/zylo_liquid/models.py` (2026-09-15, Phase 2 de la
migration monolithe modulaire, voir ARCHITECTURE.md). Noms de tables
Postgres inchangés, seul l'emplacement du code Python bouge.

`TruckPositionPing`/`GpsDeviceAssignment`/`TruckStopEvent` gardent une FK
stricte vers `zyloLiquidTruck.id` (table du module zylo_liquid) — décision
actée en Phase 2 : Location sert aujourd'hui presque exclusivement les
camions de Liquid, une FK stricte préserve l'intégrité référentielle sans
effort de redesign. À revoir seulement si un autre domaine a un jour
besoin de suivi GPS indépendant. SQLAlchemy résout ces FK par nom de table
au moment du mapper configure — elles fonctionnent tant que les deux
modules partagent la même `Base` (`app.core.database.Base`), sans import
Python direct entre les fichiers de modèles.

Généralisation Zylo Tanker (2026-09-16) — le deuxième consommateur anticipé
par le paragraphe ci-dessus vient d'apparaître : `GpsDevice`,
`GpsDeviceAssignment` et `TruckStopEvent` gagnent chacun une colonne
`vesselId` nullable (même mécanisme de résolution de FK par nom de table,
vers `zyloTankerVessel.id`), avec une contrainte CHECK qui interdit de
renseigner `truckId` ET `vesselId` en même temps — même patron que
`Alert.stationId`/`truckId`/`vesselId` (`app/alerts/models.py`).
`TruckPositionPing` (déjà rattachée uniquement à `gpsDeviceId`, jamais à un
véhicule directement) et `TruckTrackingLocation`/`TruckStopReconciliation`/
`TruckStopComment`/`TrackingSettings` (jamais de FK véhicule directe) n'ont
besoin d'aucune modification — voir le plan de mission pour le détail de
cette vérification."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

# ================================================================
# Tracking GPS des camions-citernes (mission « tracking », étape 1 —
# position + arrêts sur carte, 2026-09-11) — même schéma que la
# télémétrie Holykell des cuves : compte/appareil enregistré → journal
# brut append-only → état dérivé calculé séparément, jamais dupliqué
# dans le brut. Traccar (passerelle protocole, hors périmètre de ce
# code) pousse les positions déjà normalisées ; ce module ne parle
# jamais un protocole boîtier propriétaire.
# ================================================================


class GpsIngestCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Secret d'ingestion par organisation — l'endpoint webhook GPS n'est
    jamais appelé par un utilisateur connecté (Traccar n'a pas de compte
    Zylo Office), donc pas d'authentification JWT possible ici. Même
    esprit que `HolykellAccount` : des identifiants externes scopés à une
    organisation, jamais un secret global partagé entre organisations."""

    __tablename__ = "zyloLiquidGpsIngestCredential"
    __table_args__ = (
        UniqueConstraint("organizationId", name="uq_zlGpsIngestCredential_org"),
        {"comment": "Secret d'ingestion GPS par organisation — valide l'endpoint webhook, jamais un accès utilisateur."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    secretToken: Mapped[str] = mapped_column(String(100), nullable=False)


class GpsDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Boîtier GPS enregistré — référentiel réseau, même portée que
    `Truck`/`Vessel`. `deviceIdentifier` est l'IMEI/numéro de série du
    boîtier, fourni par Traccar dans chaque position pour retrouver le
    véhicule correspondant. `truckId`/`vesselId` nullables : un boîtier
    peut être enregistré avant d'être posé sur un véhicule précis — jamais
    les deux à la fois (voir la contrainte CHECK)."""

    __tablename__ = "zyloLiquidGpsDevice"
    __table_args__ = (
        UniqueConstraint("organizationId", "deviceIdentifier", name="uq_zlGpsDevice_org_identifier"),
        CheckConstraint("NOT (\"truckId\" IS NOT NULL AND \"vesselId\" IS NOT NULL)", name="ck_zlGpsDevice_truck_or_vessel"),
        {"comment": "Boîtier GPS — référentiel réseau, rattaché optionnellement à un camion OU un navire, jamais les deux."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    truckId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="SET NULL"), nullable=True, index=True)
    vesselId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloTankerVessel.id", ondelete="SET NULL"), nullable=True, index=True)
    deviceIdentifier: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class TruckPositionPing(UUIDPrimaryKeyMixin, Base):
    """Journal brut append-only des positions GPS — jamais modifié après
    insertion, même discipline que `TankMeasurement`. `rawPayload`
    conserve le JSON transmis par Traccar tel quel, pour audit/diagnostic,
    jamais réinterprété ailleurs que dans le calcul dérivé."""

    __tablename__ = "zyloLiquidTruckPositionPing"
    __table_args__ = (
        Index("ix_zlTruckPositionPing_gpsDeviceId_recordedAt", "gpsDeviceId", "recordedAt"),
        {"comment": "Position GPS brute — append-only, jamais modifiée. L'état dérivé (trajet/arrêts) est calculé séparément."},
    )

    gpsDeviceId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidGpsDevice.id", ondelete="RESTRICT"), nullable=False, index=True)
    recordedAt: Mapped[datetime] = mapped_column(nullable=False)
    receivedAt: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accuracyMeters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    speedKmh: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    rawPayload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TruckStopEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Arrêt détecté — état dérivé et persisté (même esprit que
    `DeliveryDetected`), calculé à partir du flux de `TruckPositionPing`
    par l'algorithme `_scan_truck_stops` (même state machine que la
    détection de livraison : ancre stable + confirmation après N minutes).
    `endAt` NULL = arrêt toujours en cours."""

    __tablename__ = "zyloLiquidTruckStopEvent"
    __table_args__ = (
        Index("ix_zlTruckStopEvent_truckId_startAt", "truckId", "startAt"),
        Index("ix_zlTruckStopEvent_vesselId_startAt", "vesselId", "startAt"),
        CheckConstraint("\"reconciliationStatus\" IN ('none','pending','resolved')", name="ck_zlTruckStopEvent_reconciliationStatus"),
        CheckConstraint(
            "((\"truckId\" IS NOT NULL)::int + (\"vesselId\" IS NOT NULL)::int) = 1",
            name="ck_zlTruckStopEvent_truck_xor_vessel",
        ),
        {"comment": "Arrêt détecté d'un camion ou d'un navire — dérivé du flux de positions, jamais un second système de vérité."},
    )

    truckId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="RESTRICT"), nullable=True, index=True)
    vesselId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloTankerVessel.id", ondelete="RESTRICT"), nullable=True, index=True)
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    startAt: Mapped[datetime] = mapped_column(nullable=False)
    endAt: Mapped[datetime | None] = mapped_column(nullable=True)
    # Étape 2 (flux métier) — lieu reconnu automatiquement (ou tranché en
    # réconciliation), NULL = arrêt non qualifié. `reconciliationStatus`
    # distingue "jamais ambigu" (none) de "ambigu, en attente"/"tranché".
    locationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruckTrackingLocation.id", ondelete="SET NULL"), nullable=True, index=True)
    reconciliationStatus: Mapped[str] = mapped_column(String(10), nullable=False, server_default="none")


# ================================================================
# Tracking GPS des camions-citernes — étape 2 (flux métier, 2026-09) :
# lieux nommés, historique boîtier<->camion, réconciliation, commentaires.
# Traccar garde exactement son rôle de l'étape 1 (passerelle protocole) —
# toute cette logique vit ici, jamais dans Traccar (pas de géozones/
# rapports Traccar utilisés).
# ================================================================


class GpsDeviceAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historique des périodes d'association boîtier<->camion — un boîtier
    peut passer d'un camion à un autre (panne, changement de véhicule) ;
    `GpsDevice.truckId` reste un raccourci de "l'association active
    actuelle", mais toute requête sur une période passée doit résoudre
    l'association via cette table, jamais via `GpsDevice.truckId` seul
    (qui aurait déjà changé). `unassignedAt` NULL = association active."""

    __tablename__ = "zyloLiquidGpsDeviceAssignment"
    __table_args__ = (
        Index("ix_zlGpsDeviceAssignment_gpsDeviceId_assignedAt", "gpsDeviceId", "assignedAt"),
        Index("ix_zlGpsDeviceAssignment_truckId_assignedAt", "truckId", "assignedAt"),
        Index("ix_zlGpsDeviceAssignment_vesselId_assignedAt", "vesselId", "assignedAt"),
        CheckConstraint(
            "((\"truckId\" IS NOT NULL)::int + (\"vesselId\" IS NOT NULL)::int) = 1",
            name="ck_zlGpsDeviceAssignment_truck_xor_vessel",
        ),
        {"comment": "Historique des périodes d'association boîtier<->camion ou boîtier<->navire — jamais réécrit, une réaffectation ferme la ligne active et en ouvre une nouvelle."},
    )

    gpsDeviceId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidGpsDevice.id", ondelete="CASCADE"), nullable=False, index=True)
    truckId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="CASCADE"), nullable=True, index=True)
    vesselId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloTankerVessel.id", ondelete="CASCADE"), nullable=True, index=True)
    assignedAt: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    unassignedAt: Mapped[datetime | None] = mapped_column(nullable=True)


class TraccarConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Connexion à l'API Traccar de l'organisation — configurée en libre-
    service depuis Zylo Liquid (jamais par un identifiant en dur côté
    serveur, qui ne passerait pas à l'échelle multi-organisation). Utilisée
    uniquement côté serveur pour appeler `POST /api/session` puis
    `GET /api/devices` sur le Traccar de cette organisation — jamais
    exposée au navigateur. Mot de passe stocké tel quel, même pratique que
    `GpsIngestCredential.secretToken` (protégé par les accès base, pas de
    chiffrement colonne dans ce projet à ce stade)."""

    __tablename__ = "zyloLiquidTraccarConnection"
    __table_args__ = (
        UniqueConstraint("organizationId", name="uq_zlTraccarConnection_org"),
        {"comment": "Identifiants de connexion à l'API Traccar de l'organisation — jamais exposés au navigateur."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    baseUrl: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)


class TruckTrackingLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lieu nommé posé sur la carte (port, entrepôt, dépôt fournisseur) —
    posé comme un point Google Maps (position actuelle / coordonnées /
    recherche d'adresse), jamais une géozone dessinée. `radiusMeters` est
    une tolérance invisible pour l'utilisateur, pas un objet à dessiner.
    `status='deleted'` = suppression douce, appliquée dès qu'au moins un
    `TruckStopEvent` référence ce lieu (jamais de suppression physique
    dans ce cas — casserait l'historique déjà qualifié)."""

    __tablename__ = "zyloLiquidTruckTrackingLocation"
    __table_args__ = (
        CheckConstraint("type IN ('port','entrepot','depot_fournisseur','libre')", name="ck_zlTruckTrackingLocation_type"),
        CheckConstraint("status IN ('active','deleted')", name="ck_zlTruckTrackingLocation_status"),
        {"comment": "Lieu nommé de référence pour la reconnaissance automatique d'arrêt — jamais une géozone Traccar."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="libre")
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    radiusMeters: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default="150")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")


class TruckStopReconciliation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """File de décision humaine quand un arrêt tombe dans le rayon de
    plusieurs lieux dont les distances sont trop proches pour trancher
    automatiquement (écart < 20 %, voir `match_truck_stop_to_locations`).
    `resolvedLocationId` NULL après résolution = "aucun des deux",
    l'arrêt reste non qualifié en connaissance de cause."""

    __tablename__ = "zyloLiquidTruckStopReconciliation"
    __table_args__ = (
        CheckConstraint("status IN ('pending','resolved')", name="ck_zlTruckStopReconciliation_status"),
        {"comment": "File d'arrêts ambigus (chevauchement de lieux) en attente d'un arbitrage humain."},
    )

    stopEventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruckStopEvent.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    candidateLocationIds: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    resolvedLocationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruckTrackingLocation.id", ondelete="SET NULL"), nullable=True)
    resolvedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    resolvedAt: Mapped[datetime | None] = mapped_column(nullable=True)


class TruckStopComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commentaire humain sur un arrêt — plusieurs par arrêt, modifiable et
    supprimable (version simple assumée avec le commanditaire, pas un
    journal append-only ici). Jamais lié automatiquement au traitement
    d'une alerte (actions découplées)."""

    __tablename__ = "zyloLiquidTruckStopComment"
    __table_args__ = ({"comment": "Commentaire humain sur un arrêt de camion — modifiable/supprimable, plusieurs par arrêt."},)

    stopEventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruckStopEvent.id", ondelete="CASCADE"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class TrackingSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Réglages de tracking par organisation — remplace les constantes
    réseau fixes de l'étape 1 (`TRUCK_STOP_RADIUS_METERS_DEFAULT`/
    `TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT`) par des valeurs
    réglables ; ces constantes restent le repli si aucune ligne n'existe
    pour l'organisation (jamais de comportement cassé par défaut)."""

    __tablename__ = "zyloLiquidTrackingSettings"
    __table_args__ = (
        UniqueConstraint("organizationId", name="uq_zlTrackingSettings_org"),
        {"comment": "Réglages de tracking par organisation — repli sur les constantes réseau si absent."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    stopStabilizationMinutes: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    stopRadiusMeters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    liveViewThrottleMs: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
