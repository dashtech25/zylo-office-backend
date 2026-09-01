"""Module Zylo Liquid — Phase 1 (base de données uniquement).

Sources : `schema_complet_base_de_donnees.sql` (25 tables, 7 couches,
schéma initialement validé) comparé à la base PostgreSQL réelle
`zylo_liquid` (testée : ~590 000 mesures, 22 stations, 52 cuves). Voir
`docs/modules/zylo-liquid/phase-1-database.md` pour la comparaison complète,
la classification Core/Zylo Liquid table par table, et les tables encore
« À VALIDER » (proprietaires, users, user_station_access, user_sessions,
audit_logs, societes, reseaux) délibérément absentes de ce fichier — leur
classification dépend d'une décision architecturale sur leur recoupement
avec les tables Core déjà construites (`organization`, `user`, RBAC) et ne
doit pas être tranchée sans validation humaine explicite (règle absolue de
l'instruction : « NE DÉCIDE PAS ARBITRAIREMENT »).

Ce fichier porte uniquement les couches 1 (Télémétrie) et 2 (Référentiel)
du schéma source, plus la table `station` (couche Gold 1) dont dépendent
les cuves — les seules tables dont la classification "Zylo Liquid, pas
Core" ne fait aucun doute et dont aucune colonne ne référence une table
encore à valider.

Toute colonne calculée par trigger/fonction PL/pgSQL dans le schéma source
(checksum, network_delay_sec, margin_fcfa...) est portée ici comme colonne
simple, SANS la logique de calcul — cette logique est un algorithme métier,
explicitement hors périmètre de la Phase 1 (base de données seule)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


# ================================================================
# COUCHE 1 — TÉLÉMÉTRIE
# Noyau immuable : ce que Holykell fournit, sans interprétation métier.
# ================================================================


class HolykellAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidHolykellAccount"
    __table_args__ = (
        CheckConstraint("\"lastSyncStatus\" IN ('success','partial','failed')", name="ck_zlHolykellAccount_syncStatus"),
        {
            "comment": "Credentials et état de synchronisation d'un compte Holykell (h-smartlink.com) lié à une organisation Zylo Office. Source : table 'holykell_accounts'."
        },
    )

    # Remplace proprietaire_id (schéma source) par organizationId — utilise
    # directement le Core Zylo Office déjà existant plutôt que de dupliquer
    # la notion de "propriétaire" dans ce module (voir docstring du fichier).
    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    holykellUsername: Mapped[str] = mapped_column(String(100), nullable=False)
    holykellPassword: Mapped[str] = mapped_column(String(255), nullable=False)
    holykellTenantId: Mapped[str | None] = mapped_column(String(50), nullable=True)

    accessToken: Mapped[str | None] = mapped_column(Text, nullable=True)
    refreshToken: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokenExpiresAt: Mapped[datetime | None] = mapped_column(nullable=True)

    lastSyncAt: Mapped[datetime | None] = mapped_column(nullable=True)
    lastSyncStatus: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lastSyncError: Mapped[str | None] = mapped_column(Text, nullable=True)
    syncEnabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class HolykellDeviceRegistry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidHolykellDeviceRegistry"
    __table_args__ = (
        UniqueConstraint("holykellAccountId", "hkSensorId", name="uq_zlHolykellDevice_account_sensor"),
        UniqueConstraint("hkSensorId", name="uq_zlHolykellDevice_hkSensorId_global"),
        CheckConstraint("\"hkLastStatus\" IN (0,1)", name="ck_zlHolykellDevice_lastStatus"),
        CheckConstraint("\"sensorCategory\" IN ('physical','device')", name="ck_zlHolykellDevice_sensorCategory"),
        {
            "comment": "Registre de tous les sensors Holykell (device HK301 + sensor dénormalisés sur une seule ligne pour le chemin critique de synchronisation). Source : table 'holykell_devices_registry'."
        },
    )

    holykellAccountId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidHolykellAccount.id", ondelete="CASCADE"), nullable=False, index=True
    )

    hkGroupId: Mapped[int] = mapped_column(nullable=False)
    hkGroupName: Mapped[str] = mapped_column(String(200), nullable=False)
    hkDeviceId: Mapped[int] = mapped_column(nullable=False)
    hkDeviceName: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hkSerialNumber: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    hkProtocol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hkReportCycleSec: Mapped[int | None] = mapped_column(nullable=True)
    hkLatitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    hkLongitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    hkLastStatus: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hkLastSeenAt: Mapped[datetime | None] = mapped_column(nullable=True)

    hkSensorId: Mapped[int] = mapped_column(nullable=False, index=True)
    hkSensorName: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hkReadWriteMark: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hkUnit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hkSensorType: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hkDecimalPlaces: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=0)

    sensorCategory: Mapped[str] = mapped_column(String(10), nullable=False, default="physical")

    isMapped: Mapped[bool] = mapped_column(nullable=False, default=False)
    mappedAt: Mapped[datetime | None] = mapped_column(nullable=True)

    lastValue: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    lastValueAt: Mapped[datetime | None] = mapped_column(nullable=True)
    syncFrom: Mapped[datetime] = mapped_column(nullable=False)

    discoveredAt: Mapped[datetime] = mapped_column(nullable=False)
    isActive: Mapped[bool] = mapped_column(nullable=False, default=True)
    rawDevicePayload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TankMeasurement(Base):
    """Journal légal immuable des mesures physiques. APPEND-ONLY : jamais de
    UPDATE ni DELETE (règle absolue héritée du schéma source, à faire
    respecter au niveau applicatif en Phase 2 — aucune contrainte SQL ne
    peut empêcher un UPDATE, c'est une règle de service, pas de schéma).

    Le schéma source partitionne cette table par mois (PARTITION BY RANGE
    sur measuredAt) — non reproduit par les modèles déclaratifs SQLAlchemy
    ici (nécessite du DDL manuel dans la migration Alembic), mais documenté
    comme exigence à honorer dans la migration réelle."""

    __tablename__ = "zyloLiquidTankMeasurement"
    __table_args__ = (
        {
            "comment": "Journal immuable des mesures physiques reçues depuis Holykell — jamais converties, jamais modifiées. Partitionnée par mois (measuredAt) dans le schéma source. Source : table 'tank_measurements'."
        },
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    hkMeasurementId: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    hkSensorId: Mapped[int] = mapped_column(
        ForeignKey("zyloLiquidHolykellDeviceRegistry.hkSensorId"), nullable=False, index=True
    )
    hkDeviceSerial: Mapped[str] = mapped_column(String(100), nullable=False)
    hkSensorName: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hkReadWriteMark: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hkUnit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hkDecimalPlaces: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    measuredAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    receivedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    # networkDelaySec est une colonne GENERATED ALWAYS AS STORED dans le
    # schéma source (measuredAt -> receivedAt) — calcul différé à la Phase 2.
    networkDelaySec: Mapped[int | None] = mapped_column(nullable=True)

    rawValue: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)

    insertedAt: Mapped[datetime] = mapped_column(nullable=False)
    # checksum est calculé par trigger PL/pgSQL dans le schéma source —
    # calcul différé à la Phase 2, colonne conservée pour fidélité au schéma.
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    isCorrection: Mapped[bool] = mapped_column(nullable=False, default=False)
    correctsMeasurementId: Mapped[int | None] = mapped_column(nullable=True)
    rawHolykellResponse: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ================================================================
# COUCHE 2 — RÉFÉRENTIEL (+ station, dont les cuves dépendent)
# ================================================================


class FuelProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidFuelProduct"
    __table_args__ = {"comment": "Référentiel des carburants et leurs propriétés physiques/financières. Source : table 'fuel_products'."}

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    densityGPerCm3: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    currentPriceFcfa: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    currentCostFcfa: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    displayColor: Mapped[str | None] = mapped_column(String(7), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Station(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidStation"
    __table_args__ = (
        UniqueConstraint("organizationId", "code", name="uq_zlStation_org_code"),
        CheckConstraint("status IN ('active','maintenance','inactive')", name="ck_zlStation_status"),
        {
            "comment": "Station-service physique appartenant à une organisation. Rattachements géographiques (cityId) alignés sur la base réelle testée, plus riche que le schéma initial (city/region en texte libre) — voir phase-1-database.md §5. Source : table 'stations'."
        },
    )

    # Remplace proprietaire_id par organizationId (voir HolykellAccount).
    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)

    # Géolocalisation normalisée — confirmée par la base réelle (cityId),
    # remplace les colonnes city/region en texte libre du schéma initial.
    cityId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("city.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Africa/Douala")

    holykellGroupId: Mapped[int | None] = mapped_column(nullable=True)

    openingTime: Mapped[str] = mapped_column(String(8), nullable=False, default="06:00")
    closingTime: Mapped[str] = mapped_column(String(8), nullable=False, default="22:00")
    is24h: Mapped[bool] = mapped_column(nullable=False, default=False)

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    integrationDate: Mapped[date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Champs commerce/amenities confirmés par la base réelle, absents du
    # schéma initial (évolution ultérieure, voir phase-1-database.md §5).
    exploitationType: Mapped[str] = mapped_column(String(20), nullable=False, default="propre")
    hasShop: Mapped[bool] = mapped_column(nullable=False, default=False)
    shopName: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shopSurfaceM2: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    hasLavage: Mapped[bool] = mapped_column(nullable=False, default=False)
    hasVidange: Mapped[bool] = mapped_column(nullable=False, default=False)
    hasGazDomestique: Mapped[bool] = mapped_column(nullable=False, default=False)
    nbPistes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    surfaceTotaleM2: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)


class Tank(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidTank"
    __table_args__ = (
        UniqueConstraint("stationId", "tankNumber", name="uq_zlTank_station_number"),
        CheckConstraint("\"capacityLiters\" > 0", name="ck_zlTank_capacity_positive"),
        CheckConstraint("\"dataSourceType\" IN ('console','direct')", name="ck_zlTank_dataSourceType"),
        {"comment": "Cuve physique installée dans une station. Source : table 'tanks'."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fuelProductId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id"), nullable=False, index=True
    )

    tankNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    displayName: Mapped[str] = mapped_column(String(100), nullable=False)

    capacityLiters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    calibratedCapacityLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    tankHeightMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    dataSourceType: Mapped[str] = mapped_column(String(10), nullable=False, default="console")

    alertLowPercent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=20.00)
    alertCriticalPercent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=10.00)
    alertHighPercent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=95.00)
    alertWaterMaxMm: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=25.00)

    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    productSince: Mapped[date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TankSensorMapping(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "zyloLiquidTankSensorMapping"
    __table_args__ = (
        UniqueConstraint("hkSensorId", "measurementType", "tankId", name="uq_zlTankSensorMapping_sensor_type_tank"),
        CheckConstraint(
            "\"measurementType\" IN ('product_level','water_level','temperature')",
            name="ck_zlTankSensorMapping_measurementType",
        ),
        {
            "comment": "Pont entre un sensor Holykell (couche télémétrie) et une cuve Zylo Liquid (couche référentiel). Source : table 'tank_sensor_mapping'."
        },
    )

    hkSensorId: Mapped[int] = mapped_column(
        ForeignKey("zyloLiquidHolykellDeviceRegistry.hkSensorId"), nullable=False, index=True
    )
    tankId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id"), nullable=False, index=True
    )
    measurementType: Mapped[str] = mapped_column(String(20), nullable=False)

    validFrom: Mapped[datetime] = mapped_column(nullable=False)
    validUntil: Mapped[datetime | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)

    createdAt: Mapped[datetime] = mapped_column(nullable=False)


class TankCalibrationPoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "zyloLiquidTankCalibrationPoint"
    __table_args__ = (
        UniqueConstraint("tankId", "heightMm", name="uq_zlTankCalibrationPoint_tank_height"),
        {
            "comment": "Point de calibration (hauteur mm -> volume litres) d'une cuve. Interpolation linéaire appliquée en Phase 2 (algorithme, hors périmètre de cette phase). Source : table 'tank_calibration_points'."
        },
    )

    tankId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=False, index=True
    )
    heightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    volumeLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
