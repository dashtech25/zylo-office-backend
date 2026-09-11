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
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
        # Requis par `_measurement_at_or_before` (service.py ~L2441) :
        # "dernière mesure connue avant un instant, pour un capteur" —
        # WHERE hkSensorId IN (...) AND measuredAt <= X ORDER BY measuredAt
        # DESC LIMIT 1. Sans cet index composite, Postgres balaye l'index
        # measuredAt seul et filtre hkSensorId après coup (mesuré :
        # Rows Removed by Filter proche du total de la table). measuredAt
        # DESC pour matcher l'ORDER BY ... DESC du pattern de requête.
        Index(
            "ix_zyloLiquidTankMeasurement_hkSensorId_measuredAt",
            "hkSensorId",
            text('"measuredAt" DESC'),
        ),
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
    __table_args__ = (
        UniqueConstraint("organizationId", "code", name="uq_zlFuelProduct_org_code"),
        {
            "comment": "Référentiel des carburants et leurs propriétés physiques/financières. Source : table 'fuel_products'. "
            "organizationId ajouté à la construction de l'endpoint 1 (Point 3 §9.3) : absent du schéma source et de la base "
            "réelle (réseau unique testé), mais requis par cohérence avec l'isolation multi-tenant de toutes les autres tables "
            "Zylo Liquid (Station, Tank...) — sans cette colonne, une organisation verrait/modifierait le référentiel carburant "
            "d'une autre. Le code redevient unique par organisation, plus globalement."
        },
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    densityGPerCm3: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    # Coefficient de dilatation thermique (alpha, par °C) — confirmé absent
    # en Phase 1 (Point 2 §7 "Modèles manquants"), ajouté à la construction
    # de l'endpoint 7 qui en a besoin pour la correction à 15°C (Point 5
    # §5.2). Nullable : sans valeur connue, aucune correction n'est
    # appliquée plutôt que d'inventer un coefficient (endpoint 7, §3.1).
    thermalExpansionCoefficient: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    # currentPriceFcfa/currentCostFcfa retirés (audit Configuration
    # carburant P1 §B) : dénormalisation FCFA de l'ancien schéma, jamais mise
    # à jour par aucun service — `PriceHistory` est la seule source de
    # vérité pour un prix. Le "prix unitaire courant" affiché à l'écran vient
    # désormais de `TankCurrentStateResponse.unitPriceAmount`, résolu en
    # temps réel via `_resolve_applicable_price`.
    displayColor: Mapped[str | None] = mapped_column(String(7), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class StationFuelProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidStationFuelProduct"
    __table_args__ = (
        UniqueConstraint("stationId", "fuelProductId", name="uq_zlStationFuelProduct_station_product"),
        {
            "comment": "Association explicite « ce produit est vendu dans cette station » — jamais déduite implicitement "
            "d'une cuve existante ou d'un prix déjà saisi (page_configuration.md §15/§41). `active=false` retire le "
            "produit de la station sans perdre l'historique de prix déjà enregistré pour ce couple (même philosophie "
            "que FuelProduct.active : jamais de suppression réelle d'une donnée référencée ailleurs)."
        },
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fuelProductId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(nullable=False, default=True)

    # Page Exploitation (Centre administratif de la station) — seuils
    # commerciaux de réassort, jamais un seuil inventé par défaut (NULL =
    # non défini, jamais un statut "critique" calculé à partir d'une valeur
    # inventée). Distincts des seuils physiques de `Tank`
    # (heightAlarmMm/heightAlertMm/lowAlarmMm, en mm, par cuve, alarme
    # capteur) — ici en litres, par produit et par station, décision
    # commerciale de réapprovisionnement.
    minThresholdLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    criticalThresholdLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    safetyStockLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)


class StationService(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalogue des services proposés par une station (page Exploitation,
    onglet Services) — remplace, pour cette page, les 4 booléens de
    `Station` (hasShop/hasLavage/hasVidange/hasGazDomestique), qui restent
    en place ailleurs (jamais retirés, jamais une migration destructive).
    `type` en texte libre (comme `Station.exploitationType`) : la maquette
    montre un bouton « + Ajouter un service » — liste ouverte, jamais figée
    à une énumération fermée."""

    __tablename__ = "zyloLiquidStationService"
    __table_args__ = ({"comment": "Service proposé par une station — type libre, disponibilité togglée."},)

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    available: Mapped[bool] = mapped_column(nullable=False, default=True)


class StationProductPricingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Politique commerciale d'un produit à une station (page Exploitation,
    onglet Configuration commerciale) — par (station, produit), aligné sur
    la portée de `PriceHistory` (décision commanditaire confirmée). Distinct
    de `PriceHistory` elle-même : ceci décrit COMMENT le prix est fixé
    (type/période/promotions/règles), jamais une valeur de prix."""

    __tablename__ = "zyloLiquidStationProductPricingPolicy"
    __table_args__ = (
        UniqueConstraint("stationId", "fuelProductId", name="uq_zlStationProductPricingPolicy_station_product"),
        {"comment": "Politique commerciale (type/période/promotions/règles) d'un produit à une station — jamais une valeur de prix, voir PriceHistory."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False, index=True)
    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="CASCADE"), nullable=False, index=True)
    policyType: Mapped[str] = mapped_column(String(30), nullable=False, server_default="prix_fixe")
    applicationPeriod: Mapped[str] = mapped_column(String(30), nullable=False, server_default="toujours_actif")
    promotionsEnabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Les 3 règles spéciales fixes de la maquette — jamais un texte libre
    # pour ces 3-là, la maquette montre exactement 3 cases à cocher.
    differentPriceByPeriod: Mapped[bool] = mapped_column(nullable=False, default=False)
    volumeDiscount: Mapped[bool] = mapped_column(nullable=False, default=False)
    corporateRate: Mapped[bool] = mapped_column(nullable=False, default=False)


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
    # Dérogation explicite de devise (page_caisse_configuration_audit, P1
    # §E.4, inspirée de `currency_override_id` de l'ancien Zylo/Odoo) : une
    # station facturant dans une devise différente de celle héritée de sa
    # ville/pays (ex. station frontalière) peut la fixer ici sans avoir
    # besoin d'une vraie hiérarchie géographique de devises. `NULL` = pas de
    # dérogation, la devise reste dérivée de `cityId` (jamais une devise
    # inventée par défaut si aucune des deux résolutions n'aboutit).
    currencyOverrideId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=True
    )

    holykellGroupId: Mapped[int | None] = mapped_column(nullable=True)

    openingTime: Mapped[str] = mapped_column(String(8), nullable=False, default="06:00")
    closingTime: Mapped[str] = mapped_column(String(8), nullable=False, default="22:00")
    is24h: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Jours de fermeture hebdomadaire — CSV de jours ISO (1=lundi..7=dimanche),
    # ex. "7" (fermé le dimanche) ou "6,7" (fermé le week-end). NULL/vide =
    # ouvert tous les jours, jamais une valeur inventée par défaut (mission
    # « amélioration zylo liquid », page de station.docx : champ absent avant
    # ce commit, seules les heures quotidiennes existaient).
    closedWeekdays: Mapped[str | None] = mapped_column(String(20), nullable=True)

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

    # Informations administratives/fiscales — Centre administratif et
    # opérationnel de la station (domaine « Finances »). `bankAccountInfo`
    # est délibérément séparé du reste dans les schémas Pydantic et gardé
    # derrière une permission dédiée `STATION_FINANCIAL_READ` (même principe
    # que `PRICE_HISTORY_READ` déjà utilisé pour masquer une valorisation à
    # certains rôles) — jamais exposé par le StationResponse standard.
    taxId: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billingAddress: Mapped[str | None] = mapped_column(Text, nullable=True)
    costCenterCode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bankAccountInfo: Mapped[str | None] = mapped_column(Text, nullable=True)


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

    # Seuils en millimètres, saisis par cuve — jamais une constante globale
    # (exigence explicite de fonctionnalite-mvp.md §1.2, cohérente avec la
    # comparaison H_net aux seuils du Point 13). Remplacent les 3 champs
    # pourcentage (alertLowPercent/alertCriticalPercent/alertHighPercent) de
    # la Phase 1, jamais exposés par aucun endpoint et incompatibles avec cet
    # algorithme — constat fait à la construction de l'endpoint 3 (issue #27).
    heightAlarmMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    heightAlertMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    lowAlarmMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
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


class DeliveryDetected(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Livraison détectée automatiquement (Point 2 §3.3, Point 8 §8.3) —
    modèle confirmé absent en Phase 1 (Point 2 §7 "Modèles manquants"),
    créé à la construction de l'endpoint 10 (issue #41). Alimentée par un
    traitement de fond (détection sur l'historique des mesures) — aucun
    endpoint de création manuelle n'existe (contrat explicite)."""

    __tablename__ = "zyloLiquidDeliveryDetected"
    __table_args__ = (
        UniqueConstraint("tankId", "startTime", name="uq_zlDeliveryDetected_tank_start"),
        {"comment": "Livraison détectée automatiquement par l'algorithme de Point 8 §8.3 — jamais créée manuellement."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=False, index=True
    )
    startTime: Mapped[datetime] = mapped_column(nullable=False, index=True)
    startHeightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    startVolumeLiters: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    endTime: Mapped[datetime] = mapped_column(nullable=False)
    endHeightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    endVolumeLiters: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    volumeLiters: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)


class LeakageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Événement de test de fuite statique (Point 2 §3.4, Point 10 §10.3 —
    version finale corrigée EPA avec soustraction eau + correction
    thermique). Modèle confirmé absent en Phase 1 (Point 2 §7), créé à la
    construction de l'endpoint 11 (issue #43). Alimentée par un test
    explicite (station à l'arrêt) — aucun endpoint de création manuelle."""

    __tablename__ = "zyloLiquidLeakageRecord"
    __table_args__ = (
        UniqueConstraint("tankId", "startTime", "endTime", name="uq_zlLeakageRecord_tank_window"),
        CheckConstraint("result IN ('normal','anomaly')", name="ck_zlLeakageRecord_result"),
        {"comment": "Résultat d'un test de fuite statique — jamais créé manuellement."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=False, index=True
    )
    startTime: Mapped[datetime] = mapped_column(nullable=False, index=True)
    startHeightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    startWaterHeightMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    startTemperatureC: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    endTime: Mapped[datetime] = mapped_column(nullable=False)
    endHeightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    endWaterHeightMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    endTemperatureC: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    leakRateLph: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False)


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alerte (Point 2 chapitre 4, Point 13 §13.4) — modèle confirmé absent
    en Phase 1 (Point 2 §7), créé à la construction de l'endpoint 12
    (issue #45). Partage une table unique entre tous les déclencheurs —
    jamais un second modèle d'alerte par famille.

    Refonte alertes Étape 2 (2026-09) — décisions D2/D3/D4 :
    - `stationId` toujours renseigné (portée minimale garantie même sans
      cuve) ; `tankId`/`productId` selon le type (une cuve précise, ou un
      produit à l'échelle de la station — ex. `price_missing`).
    - `sourceType`/`sourceId` : référence logique vers l'entité qui a
      réellement déclenché l'alerte (`DeliveryDetected`, `DeliveryDeclaration`,
      `LeakageRecord`...) — jamais une FK stricte (polymorphe), pour permettre
      un vrai diagnostic sans dupliquer un second schéma par famille.
    - `severity` calculée par le service au moment de la création — plus
      jamais dérivée côté frontend depuis un `Set` de types dupliqué.
    - Cycle de vie à 3 états (`active`/`acknowledged`/`resolved`, D3) :
      l'acquittement (qui/quand) est une déclaration d'intention humaine,
      distincte de la résolution. La résolution elle-même distingue
      `resolutionMethod` : `auto_verified` (le service a relu la condition
      réelle et constaté sa disparition — `resolvedByUserId` reste NULL) vs
      `manual_justified` (aucune vérification automatique possible pour ce
      type, fermeture manuelle avec `resolutionNote` obligatoire et
      `resolvedByUserId` renseigné). Un clic humain ne referme donc plus
      jamais silencieusement une alerte pour laquelle une vérité mesurable
      existe (Point 2 §11 de la mission alertes)."""

    __tablename__ = "zyloLiquidAlert"
    __table_args__ = (
        CheckConstraint(
            "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
            "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
            "'price_missing','sensor_mapping_missing','calibration_missing')",
            name="ck_zlAlert_type",
        ),
        CheckConstraint("status IN ('active','acknowledged','resolved')", name="ck_zlAlert_status"),
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="ck_zlAlert_severity",
        ),
        CheckConstraint(
            "\"resolutionMethod\" IS NULL OR \"resolutionMethod\" IN ('auto_verified','manual_justified')",
            name="ck_zlAlert_resolutionMethod",
        ),
        {"comment": "Alerte déclenchée automatiquement — cycle de vie active/acknowledged/resolved (refonte 2026-09, voir docstring)."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tankId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=True, index=True
    )
    productId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active", index=True)

    # Référence logique (jamais une FK stricte — polymorphe par nature) vers
    # l'entité qui a réellement produit l'alerte, pour permettre un
    # diagnostic contextualisé (D4). NULL pour les types sans entité source
    # dédiée (ex. seuils de niveau, dérivés directement de la mesure).
    sourceType: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sourceId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    triggeredAt: Mapped[datetime] = mapped_column(nullable=False)
    triggeredValue: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    thresholdValue: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    acknowledgedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    acknowledgedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    resolvedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    resolvedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    resolutionMethod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolutionNote: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historique des prix (Point 2 §7.3-7.5). Extension du modèle du
    schéma source (table `price_history`, déjà auditée en Phase 1, trigger
    d'audit confirmé permettant UPDATE — voir
    niveau_1_base_de_donnees_et_monetisation.md §14) : `price_fcfa`/
    `cost_fcfa` remplacés par `priceAmount`/`costAmount` + `currencyId`
    (Core, endpoint 14) pour supporter le multi-devise réel du réseau
    (§24 de la même étude) — décision prise à la construction de cet
    endpoint (issue #51)."""

    __tablename__ = "zyloLiquidPriceHistory"
    __table_args__ = (
        UniqueConstraint("stationId", "fuelProductId", "effectiveFrom", name="uq_zlPriceHistory_station_product_effectiveFrom"),
        # PostgreSQL ne considère jamais deux NULL comme égaux dans une
        # UniqueConstraint classique : sans cet index partiel, la contrainte
        # ci-dessus n'empêcherait pas deux lignes « prix par défaut réseau »
        # (stationId NULL, audit Configuration carburant P2 §E) pour le même
        # produit et la même date — jamais deux prix par défaut concurrents.
        # currencyId fait partie de la clé (refonte multi-devise, Phase 4
        # §1 de refonte-configuration-zylo-liquid.md) : un même produit doit
        # pouvoir avoir un prix réseau simultané dans plusieurs devises —
        # seule une paire (devise, date) identique doit rester unique.
        Index(
            "uq_zlPriceHistory_networkDefault_product_effectiveFrom",
            "fuelProductId", "currencyId", "effectiveFrom",
            unique=True,
            postgresql_where='"stationId" IS NULL',
        ),
        CheckConstraint('"priceAmount" > 0', name="ck_zlPriceHistory_priceAmount_positive"),
        {"comment": "Historique des prix — changement réel = insertion, correction = UPDATE ciblé. Source : table 'price_history'."},
    )

    # NULL = prix par défaut du réseau (pas rattaché à une station précise),
    # audit Configuration carburant P2 §E — inspiré de la résolution à 2
    # niveaux (station précise / défaut société) déjà validée dans l'ancien
    # Zylo/Odoo (`zylo.liquid.fuel.price._get_current_price`). Résolu par
    # `_resolve_applicable_price` : priorité au prix propre à la station,
    # repli sur le prix par défaut réseau seulement si aucun n'existe.
    stationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    fuelProductId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    priceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    costAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    effectiveFrom: Mapped[datetime] = mapped_column(nullable=False, index=True)
    changeReason: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)


class TankCashDailyAggregate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cache d'un jour de caisse déjà clos, par cuve (audit Caisse P2 §E.3
    — performance sur les périodes longues, 30 jours). Ne remplace jamais
    le calcul à la demande : `service._get_or_compute_tank_cash_for_day`
    ne consulte cette table que pour une journée entière déjà terminée
    depuis au moins quelques heures (jamais « aujourd'hui », jamais une
    journée encore susceptible de recevoir une mesure en retard — cas K
    de page_caisse.md). Ne porte jamais les segments (traçabilité) : un
    clic sur une cuve recalcule toujours en direct via
    `_compute_tank_cash`, cette table ne sert qu'aux totaux agrégés des
    vues réseau/station."""

    __tablename__ = "zyloLiquidTankCashDailyAggregate"
    __table_args__ = (
        UniqueConstraint("tankId", "cashDate", name="uq_zlTankCashDailyAggregate_tank_date"),
        {"comment": "Cache des totaux de caisse par cuve et par jour clos — jamais la source de vérité, un recalcul reste toujours possible."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=False, index=True)
    # Nommée `cashDate` (pas `date`) : un attribut de classe portant
    # exactement le nom du type importé `date` casse la résolution du type
    # SQLAlchemy à l'exécution (`Mapped[date]` se retrouve à pointer vers
    # l'attribut lui-même plutôt que vers `datetime.date`).
    cashDate: Mapped[date] = mapped_column(nullable=False, index=True)
    volumeSoldLiters: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    volumeNotCalculableReason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    monetaryValue: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    currencyCode: Mapped[str | None] = mapped_column(String(3), nullable=True)
    monetaryValueNotCalculableReason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)


# ================================================================
# Couche déclarative — processus-double-sources-verite, Phase 5 à 8.
# Un fait opérationnel constaté par un humain, distinct par nature de la
# télémétrie ci-dessus (jamais append-only au même sens : modifiable par son
# auteur tant que `lifecycleStatus = 'declared'`, cf. Phase 5 §3). Chaque
# type de déclaration reste sa propre table (Phase 5 §1 : jamais une table
# générique unique) — `DeclarationMixin` ne crée aucune table partagée,
# seulement des colonnes répétées par convention Python.
# ================================================================


class DeclarationMixin:
    """Socle commun à toute déclaration opérationnelle (Phase 5 §2 de
    processus-double-sources-verite/05-modele-declaratif.md). `stationId` est
    résolu à la saisie depuis la portée de l'auteur, jamais redemandé (même
    mécanisme que le scoping RBAC déjà en place pour Station/Tank/PriceHistory)
    — la valeur est portée ici, sa résolution reste une responsabilité du
    service, pas du modèle. `lifecycleStatus` n'a que deux valeurs stockées :
    Phase 5 §3 précise qu'il n'existe aucun état intermédiaire "validée mais
    encore modifiable" — le passage à `locked` est immédiat au moment du
    rapprochement/de la validation."""

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    eventAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    declaredAt: Mapped[datetime] = mapped_column(nullable=False)
    lifecycleStatus: Mapped[str] = mapped_column(String(10), nullable=False, server_default="declared")
    changeReason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeliveryDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Réception de livraison déclarée par un humain (Phase 3 §12, priorité
    1) — jamais confondue avec `DeliveryDetected` ci-dessus (télémétrique,
    algorithmique) : les deux existent en parallèle, rapprochées seulement
    par le mécanisme de la Phase 6, jamais fusionnées."""

    __tablename__ = "zyloLiquidDeliveryDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlDeliveryDeclaration_lifecycleStatus"),
        {"comment": "Réception de livraison déclarée — distincte de DeliveryDetected (télémétrique)."},
    )

    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Libellé libre conservé pour les lignes historiques et les saisies sans
    # référence ; quand `supplierId` est renseigné, le service le fige au nom
    # du fournisseur au moment de la saisie — snapshot documentaire (même
    # principe que Payment.exchangeRateApplied), jamais une seconde source de
    # vérité pour le rapprochement (Phase 6 ne raisonne que sur les volumes).
    supplierName: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Références de la couche Approvisionnement (couche ci-dessus) — toutes
    # NULLables : les lignes antérieures à l'existence de ces référentiels
    # restent valides sans elles, le rapprochement n'en dépend pas.
    supplierId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSupplier.id", ondelete="RESTRICT"), nullable=True, index=True)
    truckId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="RESTRICT"), nullable=True, index=True)
    purchaseOrderId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPurchaseOrder.id", ondelete="RESTRICT"), nullable=True, index=True)
    declaredVolumeLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    # Structuré (pas une simple pièce jointe) : pratique courante confirmée
    # par la recherche externe (Phase 4 v2 §7 de 04-matrice-roles-actions-v2.md).
    deliveryNoteReference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDeliveryDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ShiftCashDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Prise/fin de poste + caisse déclarée (Phase 3 §12) — rapprochée avec
    `TankCashDailyAggregate` (agrégat télémétrique existant, Phase 6 §4.2),
    jamais un nouveau calcul télémétrique."""

    __tablename__ = "zyloLiquidShiftCashDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlShiftCashDeclaration_lifecycleStatus"),
        {"comment": "Prise/fin de poste et caisse déclarées, par cuve — rapprochée avec TankCashDailyAggregate."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    shiftStart: Mapped[datetime] = mapped_column(nullable=False)
    shiftEnd: Mapped[datetime] = mapped_column(nullable=False)
    openingReadingMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    closingReadingMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    declaredCashAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftCashDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ManualGaugingDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jaugeage manuel de contrôle (Phase 3 §12) — rapproché avec la mesure
    `TankMeasurement` la plus proche dans le temps (Phase 6 §4.1), jamais un
    remplacement de la télémétrie."""

    __tablename__ = "zyloLiquidManualGaugingDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlManualGaugingDeclaration_lifecycleStatus"),
        CheckConstraint("method IN ('dipstick','gauge_pole','other')", name="ck_zlManualGaugingDeclaration_method"),
        {"comment": "Jaugeage manuel de contrôle — rapproché avec TankMeasurement, jamais un remplacement."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    declaredHeightMm: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidManualGaugingDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


class QualityCheckDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Contrôle qualité/eau déclaré (Phase 3 §12) — rapproché par
    présence/absence d'une `Alert` de type `water` sur la même cuve dans une
    fenêtre autour de l'instant déclaré (Phase 6 §4.1) : une absence
    d'alerte ne signifie jamais que la déclaration est fausse, seulement
    que le capteur ne l'a pas détectée à son propre seuil."""

    __tablename__ = "zyloLiquidQualityCheckDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlQualityCheckDeclaration_lifecycleStatus"),
        CheckConstraint("method IN ('dipstick','water_paste','other')", name="ck_zlQualityCheckDeclaration_method"),
        {"comment": "Contrôle qualité/eau déclaré — rapproché par présence d'une Alert de type water."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    waterDetected: Mapped[bool] = mapped_column(nullable=False)
    waterHeightMm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidQualityCheckDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


class LeakTestDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Test de fuite déclenché manuellement (Phase 3 §12) — distinct de
    `LeakageRecord` ci-dessus (résultat de l'algorithme automatique, jamais
    actionné en production à ce jour, Phase 1 de l'autre mission). Le
    rapprochement reste théorique tant que l'algorithme n'est pas activé
    (Phase 6 §3)."""

    __tablename__ = "zyloLiquidLeakTestDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlLeakTestDeclaration_lifecycleStatus"),
        CheckConstraint("result IN ('normal','anomaly')", name="ck_zlLeakTestDeclaration_result"),
        {"comment": "Test de fuite déclenché manuellement — distinct de LeakageRecord (algorithmique)."},
    )

    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidLeakTestDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


class IncidentDeclaration(DeclarationMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Incident/observation libre (Phase 3 §12) — volontairement générique
    dans sa propre entité (Phase 5 §1, exception assumée à la règle "pas de
    table générique") : seule la catégorie est contrôlée, jamais le texte."""

    __tablename__ = "zyloLiquidIncidentDeclaration"
    __table_args__ = (
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlIncidentDeclaration_lifecycleStatus"),
        CheckConstraint("category IN ('safety','equipment','quality','security','other')", name="ck_zlIncidentDeclaration_category"),
        {"comment": "Incident/observation libre — catégorie contrôlée, description toujours libre."},
    )

    tankId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidIncidentDeclaration.id", ondelete="RESTRICT"), nullable=True)
    reconciledWithId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciledWithType: Mapped[str | None] = mapped_column(String(40), nullable=True)


# ================================================================
# Couche Commercial (processus-double-sources-verite, Phase 5 §5, Phase 7
# §2-3) — Bloc 3. Jamais une quatrième source de vérité indépendante
# (Phase 4 v2 §3 de 04-matrice-roles-actions-v2.md) : `Sale` qualifie
# toujours une distribution déjà constatée (télémétrie ou déclaration),
# jamais un fait nouveau. Portée organisation entière pour tout sauf
# `Sale` (scopée station, comme les entités déclaratives) — Phase 7 §2.
# ================================================================


class CommercialAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Compte client/tiers commercial — nom définitif confirmé (Phase 7 §3),
    délibérément distinct de `Organization` (le tenant, jamais le même
    concept — Phase 4 v2 §11)."""

    __tablename__ = "zyloLiquidCommercialAccount"
    __table_args__ = ({"comment": "Compte client à crédit — jamais confondu avec Organization (le tenant)."},)

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    creditLimit: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Volontairement minimal — pas un module de gestion de flotte complet
    (Phase 5 §5, Phase 4 v2 §11)."""

    __tablename__ = "zyloLiquidVehicle"
    __table_args__ = ({"comment": "Référence véhicule minimale — plaque/référence, rattachée à un compte client."},)

    commercialAccountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=False, index=True)
    plateOrReference: Mapped[str] = mapped_column(String(50), nullable=False)


class Driver(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jamais un `User` Zylo — un conducteur n'est pas un utilisateur du
    système (Phase 3 §1, Phase 4 v2 §11)."""

    __tablename__ = "zyloLiquidDriver"
    __table_args__ = ({"comment": "Référence conducteur libre — jamais un compte utilisateur Zylo."},)

    commercialAccountId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


# ================================================================
# Couche Approvisionnement — fusion de la page prototype #/livraisons avec
# la couche réelle (processus-double-sources-verite, Phase 5-8). Décision du
# commanditaire : « créer toutes les tables nécessaires, même fournisseur ».
# Ce sont des référentiels réseau (portée organisation entière, même pattern
# que CommercialAccount) : fournisseur, transporteur, camion — et la commande
# d'approvisionnement (prototype `commandes`, portée station comme une
# déclaration). Les statistiques affichées par le prototype (nb livraisons,
# taux de conformité, délai moyen d'un fournisseur) ne sont JAMAIS stockées
# ici : calculées à la lecture depuis DeliveryDeclaration/DeliveryDetected.
# ================================================================


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fournisseur d'approvisionnement carburant (prototype `fournisseurs`).
    Référentiel réseau, jamais porté par les livraisons détectées (la
    télémétrie ne connaît pas son fournisseur — attribution uniquement via
    la déclaration, Phase 6). `type` reste un libellé libre : la taxonomie
    métier des fournisseurs n'est pas tranchée, aucune valeur contrainte."""

    __tablename__ = "zyloLiquidSupplier"
    __table_args__ = (
        CheckConstraint(
            "category IS NULL OR category IN ('carburant','equipement','maintenance','securite','service','autre')",
            name="ck_zlSupplier_category",
        ),
        {"comment": "Fournisseur d'approvisionnement — référentiel réseau, stats (conformité, délai) calculées, jamais stockées."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    # Refonte page Fournisseurs (amelioration/reglementation... maquette
    # fournie pour Fournisseurs) — coordonnées et contact du fournisseur,
    # jamais stockés avant : colonnes additives, `Supplier` reste le
    # référentiel réseau unique, jamais une deuxième table de coordonnées.
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contactName: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contactRole: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contactPhone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contactEmail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mission « bon de commande généré » — SIRET/RCS du fournisseur, requis
    # par le modèle français de bon de commande, jamais inventé si absent.
    taxId: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Carrier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Transporteur (prototype `transporteurs`) — référentiel réseau, même
    portée que Supplier. Distinct du fournisseur : le prototype porte les
    deux sur le bon de livraison, jamais confondus."""

    __tablename__ = "zyloLiquidCarrier"
    __table_args__ = ({"comment": "Transporteur de carburant — référentiel réseau, distinct du fournisseur."},)

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Truck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Camion-citerne du réseau (prototype `camions` : immatriculation,
    nombre de compartiments, capacité). Rattachement au transporteur
    optionnel (`carrierId` NULL = camion non attribué, souvent flotte propre
    du fournisseur) ; la plaque reste unique par organisation. `capacityLiters`
    et `compartmentsCount` sont purement descriptifs : aucun algorithme ne
    s'appuie sur la capacité d'un camion aujourd'hui."""

    __tablename__ = "zyloLiquidTruck"
    __table_args__ = (
        UniqueConstraint("organizationId", "plateNumber", name="uq_zlTruck_org_plate"),
        {"comment": "Camion-citerne du réseau — descriptif (compartiments, capacité), rattaché optionnellement à un transporteur."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    carrierId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCarrier.id", ondelete="RESTRICT"), nullable=True, index=True)
    plateNumber: Mapped[str] = mapped_column(String(50), nullable=False)
    capacityLiters: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    compartmentsCount: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


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
    `Truck`. `deviceIdentifier` est l'IMEI/numéro de série du boîtier,
    fourni par Traccar dans chaque position pour retrouver le camion
    correspondant. `truckId` nullable : un boîtier peut être enregistré
    avant d'être posé sur un camion précis."""

    __tablename__ = "zyloLiquidGpsDevice"
    __table_args__ = (
        UniqueConstraint("organizationId", "deviceIdentifier", name="uq_zlGpsDevice_org_identifier"),
        {"comment": "Boîtier GPS — référentiel réseau, rattaché optionnellement à un camion."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    truckId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="SET NULL"), nullable=True, index=True)
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
        {"comment": "Arrêt détecté d'un camion — dérivé du flux de positions, jamais un second système de vérité."},
    )

    truckId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="RESTRICT"), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    startAt: Mapped[datetime] = mapped_column(nullable=False)
    endAt: Mapped[datetime | None] = mapped_column(nullable=True)


class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commande d'approvisionnement (prototype `commandes`, portée station
    comme les entités déclaratives — jamais une colonne organizationId, la
    portée passe par la station, même mécanisme que DeclarationMixin). Une
    commande vise une cuve précise (le contrôle d'ullage de la réception se
    fait cuve par cuve) ; le produit est celui de la cuve, jamais stocké
    séparément (pas de double vérité). `status` n'a que deux états réels —
    les états intermédiaires du prototype (confirmée, en transit) décrivent
    le cycle fournisseur, hors périmètre de l'application (aucune action ne
    les déclenche) ; le passage à 'received' se fait côté service quand les
    volumes déclarés rattachés atteignent le volume commandé (jamais avant)."""

    __tablename__ = "zyloLiquidPurchaseOrder"
    __table_args__ = (
        CheckConstraint("status IN ('open','received')", name="ck_zlPurchaseOrder_status"),
        CheckConstraint('"orderedVolumeLiters" > 0', name="ck_zlPurchaseOrder_orderedVolumeLiters_positive"),
        {"comment": "Commande d'approvisionnement d'une cuve — états open/received, transition posée par le service de réception."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplierId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSupplier.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    orderReference: Mapped[str] = mapped_column(String(100), nullable=False)
    orderedVolumeLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    orderedAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    expectedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")


class StationSupplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lien station↔fournisseur — Centre administratif et opérationnel de la
    station (domaine « Fournisseurs & partenaires »). `Supplier` reste un
    référentiel réseau (voir plus haut) ; cette table déclare explicitement
    quels fournisseurs desservent une station donnée, jamais déduit
    implicitement des commandes déjà passées (même philosophie que
    `StationFuelProduct` — association explicite, `active=false` retire le
    fournisseur de la station sans perdre l'historique de commandes)."""

    __tablename__ = "zyloLiquidStationSupplier"
    __table_args__ = (
        UniqueConstraint("stationId", "supplierId", name="uq_zlStationSupplier_station_supplier"),
        {"comment": "Association explicite station <-> fournisseur du référentiel réseau."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplierId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidSupplier.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Refonte page Fournisseurs — contrat et périmètre d'intervention
    # propres à CE lien station<->fournisseur (un même fournisseur réseau
    # peut avoir un contrat différent par station) : colonnes directement
    # sur `StationSupplier`, jamais une table de contrats séparée (un seul
    # contrat courant par lien, pas d'historique de contrats à ce stade —
    # limite assumée, signalée à l'implémentation plutôt que masquée).
    contractReference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contractType: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contractStartDate: Mapped[date | None] = mapped_column(nullable=True)
    contractEndDate: Mapped[date | None] = mapped_column(nullable=True, index=True)
    # CSV libre (ex. "Cuves,Pompes,Distributeurs,AdBlue") — simplification
    # assumée plutôt qu'une table de liaison vers les équipements réels de
    # la station : le périmètre d'intervention d'un fournisseur est
    # descriptif, aucun algorithme ne s'appuie dessus aujourd'hui.
    equipmentTags: Mapped[str | None] = mapped_column(Text, nullable=True)


class Authorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Autorisation rattachée à un compte, jamais à une vente individuelle a
    priori (Phase 5 §5 — fuel voucher, Phase 4 v2 §7)."""

    __tablename__ = "zyloLiquidAuthorization"
    __table_args__ = ({"comment": "Autorisation (fuel voucher) — compte + véhicule/conducteur autorisés."},)

    commercialAccountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=False, index=True)
    vehicleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidVehicle.id", ondelete="RESTRICT"), nullable=True)
    driverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDriver.id", ondelete="RESTRICT"), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Sale(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Qualification commerciale d'une distribution déjà constatée — jamais
    un fait nouveau indépendant (Phase 4 v2 §3). Immuable après création
    (pas de cycle de vie declared/locked comme les entités opérationnelles,
    Phase 5 §4 ne lui en attribue pas un) : aucune correction en place,
    aucun endpoint de suppression."""

    __tablename__ = "zyloLiquidSale"
    __table_args__ = (
        # Élargi mission « vente-maintenant-reglementation » Bloc 3 (recherche
        # métier Phase 2 §2 : mobile money dominant au Cameroun) — additif,
        # les 4 valeurs déjà en production restent valides.
        CheckConstraint(
            "\"paymentMethod\" IN ('cash','card','fleet','credit','orange_money','mtn_momo','bank_transfer','cheque','other')",
            name="ck_zlSale_paymentMethod",
        ),
        {"comment": "Vente — qualifie une distribution déjà constatée (télémétrie ou déclaration), jamais un fait nouveau."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    eventAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False)
    quantityLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    priceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    paymentMethod: Mapped[str] = mapped_column(String(20), nullable=False)
    commercialAccountId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=True)
    vehicleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidVehicle.id", ondelete="RESTRICT"), nullable=True)
    driverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDriver.id", ondelete="RESTRICT"), nullable=True)
    declarationType: Mapped[str | None] = mapped_column(String(40), nullable=True)
    declarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class Receivable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Créance ouverte par une vente à crédit (Phase 5 §5) — jamais
    convertie automatiquement dans une autre devise (principe transversal)."""

    __tablename__ = "zyloLiquidReceivable"
    __table_args__ = (
        CheckConstraint("status IN ('open','partially_settled','settled')", name="ck_zlReceivable_status"),
        # Exactement une origine — jamais les deux, jamais aucune (extension
        # Phase 3 §2.2 / Phase 9 §1 du plan de mission : une créance boutique
        # utilise `productSaleTransactionId`, une créance carburant garde
        # `saleId`, comme avant cette extension).
        CheckConstraint(
            "(\"saleId\" IS NOT NULL)::int + (\"productSaleTransactionId\" IS NOT NULL)::int = 1",
            name="ck_zlReceivable_exactly_one_origin",
        ),
        {"comment": "Créance ouverte par une vente à crédit (carburant ou boutique) — jamais soldée par écrasement, uniquement par des Payment successifs."},
    )

    commercialAccountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Nullable depuis l'extension boutique — toutes les créances existantes
    # (créées avant cette mission) ont déjà saleId renseigné, aucune migration
    # de données nécessaire (Phase 9 §1 du plan de mission).
    saleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSale.id", ondelete="RESTRICT"), nullable=True, index=True)
    productSaleTransactionId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidProductSaleTransaction.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Événement distinct de la vente (Phase 4 v2 §2) — jamais fusionné avec
    la créance qu'il réduit. `exchangeRateApplied` : snapshot capturé au
    paiement, jamais une référence vivante (Phase 5 §5.1)."""

    __tablename__ = "zyloLiquidPayment"
    __table_args__ = ({"comment": "Paiement — réduit une créance, jamais confondu avec la vente elle-même."},)

    receivableId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidReceivable.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    paidAt: Mapped[datetime] = mapped_column(nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    exchangeRateApplied: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ================================================================
# Modèle documentaire (processus-double-sources-verite, Phase 5 §6, Bloc 5)
# — association logique tranchée par le commanditaire avant la Phase 5 : un
# fichier physique stocké une seule fois, référencé par plusieurs entités
# via `DocumentLink`, jamais dupliqué. Le stockage effectif des octets
# (S3/disque) est hors périmètre de ce modèle — `storageReference` est une
# référence opaque fournie par l'appelant, jamais interprétée ici.
# ================================================================


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidDocument"
    __table_args__ = (
        CheckConstraint("\"sensitivityLevel\" IN ('normal','restreint')", name="ck_zlDocument_sensitivityLevel"),
        {"comment": "Fichier physique référencé une seule fois — jamais dupliqué (Phase 5 §6, association logique)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    storageReference: Mapped[str] = mapped_column(String(500), nullable=False)
    fileName: Mapped[str] = mapped_column(String(255), nullable=False)
    mimeType: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uploadedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    # Extensions mission « vente-maintenant-reglementation », Phase 5 §3-5 du
    # plan de mission — colonnes additives, jamais une deuxième table de
    # métadonnées documentaires.
    sensitivityLevel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    supersedesDocumentId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDocument.id", ondelete="SET NULL"), nullable=True)
    deletedAt: Mapped[datetime | None] = mapped_column(nullable=True)


class DocumentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Table de liaison polymorphe — plusieurs `DocumentLink` peuvent
    pointer vers le même `Document` (Phase 5 §6) : c'est exactement
    l'association logique décidée par le commanditaire, jamais une copie
    physique par entité liée."""

    __tablename__ = "zyloLiquidDocumentLink"
    __table_args__ = (
        UniqueConstraint("documentId", "linkedEntityType", "linkedEntityId", name="uq_zlDocumentLink_document_entity"),
        {"comment": "Association document <-> entité — plusieurs liens possibles vers un même Document, jamais de duplication."},
    )

    documentId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDocument.id", ondelete="RESTRICT"), nullable=False, index=True)
    linkedEntityType: Mapped[str] = mapped_column(String(40), nullable=False)
    linkedEntityId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


# ================================================================
# Rapprochement (processus-double-sources-verite, Phase 6, Phase 7 §1) —
# Bloc 6 : modèles seulement, le mécanisme de calcul est la Phase 8 Bloc 7.
# ================================================================


class StationReconciliationSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Dérogation explicite par station, repli sur les constantes réseau par
    défaut si absente ou si un champ précis est NULL (Phase 7 §1) — même
    pattern que `Station.currencyOverrideId` (autre mission). Chaque
    tolérance reste une proposition de démarrage non calibrée (Phase 7
    addendum §1) tant qu'aucune donnée réelle ne l'a validée."""

    __tablename__ = "zyloLiquidStationReconciliationSettings"
    __table_args__ = (
        UniqueConstraint("stationId", name="uq_zlStationReconciliationSettings_station"),
        {"comment": "Dérogation par station aux tolérances de rapprochement — NULL par champ = repli sur le défaut réseau."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=False)
    deliveryWindowHours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    deliveryVolumeToleranceFixedLiters: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    deliveryVolumeTolerancePercent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    gaugingHeightToleranceMm: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    qualityCheckWindowHours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)


class ReconciliationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Résultat d'un rapprochement — historisé, jamais réécrit (Phase 6 §2) :
    une réévaluation crée un nouvel enregistrement, seuls les champs
    pointeurs de l'entité source (`reconciledWithId`/`reconciledWithType`)
    sont mis à jour vers le plus récent. `evaluatedByUserId` NULL = calcul
    automatique (jamais une chaîne magique 'system')."""

    __tablename__ = "zyloLiquidReconciliationRecord"
    __table_args__ = (
        CheckConstraint("family IN ('quantitative','consistency')", name="ck_zlReconciliationRecord_family"),
        CheckConstraint("status IN ('matched','discrepancy','pending','insufficient_data')", name="ck_zlReconciliationRecord_status"),
        {"comment": "Résultat historisé d'un rapprochement — jamais réécrit, une réévaluation crée une nouvelle ligne."},
    )

    subjectType: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subjectId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    counterpartType: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # String, jamais UUID : `TankMeasurement.id` (une des contreparties
    # possibles, rapprochement du jaugeage manuel) est un entier
    # auto-incrémenté, pas un UUID (seule exception du schéma, journal
    # append-only à très haut volume) — un champ texte reste correct pour
    # toutes les autres contreparties (castées en chaîne), sans ajouter une
    # seconde colonne pour ce seul cas particulier.
    counterpartId: Mapped[str | None] = mapped_column(String(64), nullable=True)
    family: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    discrepancyValue: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    discrepancyUnit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    toleranceApplied: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    evaluatedAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    evaluatedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 4 (corrigé) : ventes de
# produits boutique/non-carburant. Entité VOLONTAIREMENT séparée de `Sale`
# — `Sale` qualifie une distribution carburant déjà constatée ailleurs
# (télémétrie/déclaration, jamais un fait nouveau indépendant, cf. son
# docstring) ; une vente de produit boutique EST au contraire un fait
# nouveau et indépendant (aucune télémétrie ne la précède), elle ne doit
# donc jamais emprunter le modèle `Sale`. Panier multi-lignes : une
# transaction, plusieurs lignes produit (contrairement à `Sale`, toujours
# mono-produit car calée sur un événement de distribution unique).
# ================================================================


class ProductSaleTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Le ticket de caisse boutique — jamais réécrit après validation, une
    annulation change `status`, ne supprime rien (même discipline que
    `Sale`/`Receivable` : statuts, jamais de suppression physique)."""

    __tablename__ = "zyloLiquidProductSaleTransaction"
    __table_args__ = (
        CheckConstraint(
            "\"paymentMethod\" IN ('cash','card','orange_money','mtn_momo','bank_transfer','cheque','credit','other')",
            name="ck_zlProductSaleTransaction_paymentMethod",
        ),
        CheckConstraint("status IN ('completed','cancelled')", name="ck_zlProductSaleTransaction_status"),
        {"comment": "Vente de produit(s) boutique/non-carburant — fait nouveau et indépendant, jamais lié à une distribution déjà constatée."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    eventAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    paymentMethod: Mapped[str] = mapped_column(String(20), nullable=False)
    totalAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="completed")
    commercialAccountId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=True)
    cancelledAt: Mapped[datetime | None] = mapped_column(nullable=True)
    cancelledByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True)


class ProductSaleLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidProductSaleLine"
    __table_args__ = ({"comment": "Une ligne produit d'un ticket de caisse boutique."},)

    transactionId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidProductSaleTransaction.id", ondelete="RESTRICT"), nullable=False, index=True)
    sellableProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSellableProduct.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    unitPriceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    lineTotalAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 5 : catalogue de
# produits vendables (boutique/non-carburant). Portée station optionnelle
# (NULL = catalogue réseau), même principe que `CommercialAccount.stationId`
# (Phase 3 §2.2 du plan de mission).
# ================================================================


class SellableProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidSellableProduct"
    __table_args__ = (
        UniqueConstraint("organizationId", "barcodeValue", name="uq_zlSellableProduct_org_barcode"),
        {"comment": "Produit vendable non-carburant (boutique) — pas de gestion de stock intégrée (hors périmètre, Phase 3 §2.2 du plan de mission)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    stationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(60), nullable=True)
    barcodeValue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    unitPriceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 6 : Maintenance.
# Hiérarchie Station -> Equipment -> Intervention (deux niveaux seulement,
# Phase 3 §3.1 du plan de mission : pas de niveau "zone" intermédiaire, non
# justifié pour une station-service). Une Intervention peut référencer une
# Alert déjà existante (linkedAlertId) — réutilise le système d'alertes en
# place plutôt que d'en recréer un second.
# ================================================================


class Technician(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Entité indépendante, pas nécessairement un `User` du système — un
    technicien est souvent un prestataire externe (Phase 3 §3.3 du plan de
    mission)."""

    __tablename__ = "zyloLiquidTechnician"
    __table_args__ = ({"comment": "Technicien de maintenance — prestataire externe ou interne, pas systématiquement un compte utilisateur."},)

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linkedUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class StationStaffProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Informations de poste d'un membre du personnel (Centre administratif
    et opérationnel de la station, domaine « Personnel ») — un profil par
    personne et par organisation (pas par station : `assignedStationId` est
    un champ descriptif, la portée RBAC réelle reste `UserRole.resourceId`).
    Distinct de `Technician` (souvent un prestataire externe, pas
    nécessairement un `User`) : ce profil complète un compte `User` déjà
    membre de l'organisation (`OrganizationUser`), jamais une identité
    séparée."""

    __tablename__ = "zyloLiquidStationStaffProfile"
    __table_args__ = (
        UniqueConstraint("organizationId", "userId", name="uq_zlStationStaffProfile_org_user"),
        {"comment": "Informations de poste d'un membre du personnel — numéro d'employé, contrat, station affectée, responsable direct."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    employeeNumber: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Texte libre, même principe que Station.exploitationType — pas d'enum
    # inventé sans référentiel RH réel (ex. CDI, CDD, Stage, Intérim).
    contractType: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignedStationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="SET NULL"), nullable=True, index=True)
    directManagerUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    assignedAt: Mapped[date] = mapped_column(nullable=False)


class Equipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidEquipment"
    __table_args__ = (
        CheckConstraint("status IN ('in_service','out_of_order','out_of_service')", name="ck_zlEquipment_status"),
        {"comment": "Équipement d'une station — pompe, sonde, console, DTU, électrique, sécurité, autre."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    serialNumber: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="in_service")
    installedAt: Mapped[date | None] = mapped_column(nullable=True)
    warrantyUntil: Mapped[date | None] = mapped_column(nullable=True)
    lastMaintenanceAt: Mapped[date | None] = mapped_column(nullable=True)
    nextMaintenanceDueAt: Mapped[date | None] = mapped_column(nullable=True)


class Intervention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidIntervention"
    __table_args__ = (
        CheckConstraint("priority IN ('critical','high','medium','low')", name="ck_zlIntervention_priority"),
        CheckConstraint("type IN ('preventive','corrective')", name="ck_zlIntervention_type"),
        CheckConstraint("status IN ('planned','in_progress','closed')", name="ck_zlIntervention_status"),
        {"comment": "Intervention de maintenance sur un équipement — peut être liée à une Alert déjà existante."},
    )

    equipmentId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidEquipment.id", ondelete="RESTRICT"), nullable=False, index=True)
    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    technicianId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTechnician.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="planned")
    openedAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    plannedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    closedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    diagnosis: Mapped[str | None] = mapped_column(Text(), nullable=True)
    actionTaken: Mapped[str | None] = mapped_column(Text(), nullable=True)
    linkedAlertId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidAlert.id", ondelete="SET NULL"), nullable=True)


class SecurityEquipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Équipement de sécurité incendie / zone ATEX d'une station — Centre
    administratif et opérationnel de la station (domaine « Sécurité »).
    Reprend le format déjà validé par le prototype (`pageStation`, onglet
    `conformite`, tableau « Sécurité incendie et zones ATEX ») : label,
    dernier contrôle, prochain contrôle, statut de conformité. Distinct
    d'`Equipment` (équipement d'exploitation général) et d'`IncidentDeclaration`
    (un fait constaté, pas un inventaire récurrent à contrôler)."""

    __tablename__ = "zyloLiquidSecurityEquipment"
    __table_args__ = (
        CheckConstraint(
            "category IN ('extincteur','systeme_incendie','arret_urgence','point_evacuation','zone_atex','autre')",
            name="ck_zlSecurityEquipment_category",
        ),
        CheckConstraint(
            "\"conformityStatus\" IN ('conforme','non_conforme','a_controler')",
            name="ck_zlSecurityEquipment_conformityStatus",
        ),
        {"comment": "Équipement de sécurité incendie / zone ATEX d'une station, avec suivi de contrôle périodique."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    lastControlAt: Mapped[date | None] = mapped_column(nullable=True)
    nextControlDueAt: Mapped[date | None] = mapped_column(nullable=True)
    conformityStatus: Mapped[str] = mapped_column(String(20), nullable=False, server_default="a_controler")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ================================================================
# Mission « vente-maintenant-reglementation » — Bloc 7 : Réglementation.
# `certaintyLevel` reprend directement la classification établie en
# recherche métier (Phase 2 §1.7 du plan de mission) — jamais présenter
# une obligation incertaine comme aussi sûre qu'une obligation confirmée.
# ================================================================


class RegulatoryDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidRegulatoryDocument"
    __table_args__ = (
        CheckConstraint("\"certaintyLevel\" IN ('high','medium','low')", name="ck_zlRegulatoryDocument_certaintyLevel"),
        {"comment": "Document réglementaire d'une station — statut calculé depuis l'échéance, jamais saisi directement."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    documentType: Mapped[str] = mapped_column(String(80), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issuedAt: Mapped[date | None] = mapped_column(nullable=True)
    expiresAt: Mapped[date | None] = mapped_column(nullable=True, index=True)
    sourceReference: Mapped[str | None] = mapped_column(Text(), nullable=True)
    certaintyLevel: Mapped[str] = mapped_column(String(10), nullable=False, server_default="medium")
    supersededByDocumentId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidRegulatoryDocument.id", ondelete="SET NULL"), nullable=True
    )
    # Refonte de l'onglet Réglementation (amelioration/reglementation,
    # maquettes fournies) — champs additifs, jamais une deuxième table :
    # notes libres et responsable désigné, corrigeables via une vraie
    # UPDATE (jamais un renouvellement pour une simple faute de frappe,
    # contrairement à documentType/issuedAt/expiresAt/certaintyLevel qui
    # restent gouvernés par `renew_regulatory_document`).
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    responsibleUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True)


class RegulatoryDeclaration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidRegulatoryDeclaration"
    __table_args__ = (
        CheckConstraint("status IN ('to_produce','produced')", name="ck_zlRegulatoryDeclaration_status"),
        {"comment": "Déclaration réglementaire attendue d'une station, éventuellement déclenchée par un incident."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    triggerIncidentId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidIncidentDeclaration.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="to_produce")
    reserve: Mapped[str | None] = mapped_column(Text(), nullable=True)
