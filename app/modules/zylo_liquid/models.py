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
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
    # T-027 : mot de passe chiffré (app/core/field_crypto.py), seule valeur écrite
    # par le code. L'ancienne colonne en clair reste lisible pendant la transition
    # (repli dans app/core/field_crypto.lire_champ) puis sera supprimée par une tâche distincte.
    holykellPasswordChiffre: Mapped[str | None] = mapped_column(Text, nullable=True)
    holykellPassword: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    # Horaires personnalisés jour par jour (P2 §5.3, audit module Stations
    # 2026-09-16) — dict clé "1".."7" (jour ISO, lundi=1) → {"open": "HH:MM",
    # "close": "HH:MM", "closed": bool}. NULL = pas de personnalisation,
    # openingTime/closingTime/closedWeekdays ci-dessus restent la seule
    # source de vérité (comportement inchangé) — jamais une des deux
    # représentations resynchronisée automatiquement vers l'autre, pour ne
    # jamais écraser silencieusement un réglage déjà fait dans l'autre mode.
    weeklyHours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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


class Pump(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pompe physique de distribution, rattachée à une cuve — détermine le
    produit vendu (pas de champ produit séparé). Pour la vente/rapprochement
    (déclaration de volume vendu par pompe/shift) : la déclaration elle-même
    est hors périmètre de cette Phase, seul le référentiel CRUD est construit
    ici. Une pompe n'est jamais supprimée, seulement désactivée (`active`),
    pour préserver l'historique — même convention que `Tank.active`."""

    __tablename__ = "zyloLiquidPump"
    __table_args__ = (
        # D1 (scénario A1) : le numéro est unique PAR STATION, pas par produit ;
        # le nom généré « Pompe N° {n} – {produit} » reste unique par station.
        UniqueConstraint("stationId", "pumpNumber", name="uq_zlPump_station_number"),
        UniqueConstraint("stationId", "name", name="uq_zlPump_station_name"),
        {"comment": "Pompe de distribution rattachée à une cuve (référentiel, sans logique de déclaration de vente)."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tankId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Nom GÉNÉRÉ par le backend (« Pompe N° {pumpNumber} – {produit de la cuve} »),
    # figé en base pour garantir l'unicité et la stabilité de l'import Excel ;
    # resynchronisé quand le numéro, la cuve ou le nom du produit changent.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    pumpNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Numéro d'ordre de la pompe, unique par station.")
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serialNumber: Mapped[str | None] = mapped_column(String(100), nullable=True)
    installedOn: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


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


# Alert — déplacé vers `app/alerts/models.py` (2026-09-15, Phase 3 de la
# migration monolithe modulaire). Nom de table Postgres inchangé, FK
# conservées telles quelles (stationId/truckId/tankId/productId), aucune
# migration de données pour ce déplacement.


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
    # Structuré (pas une simple pièce jointe) : pratique courante confirmée
    # par la recherche externe (Phase 4 v2 §7 de 04-matrice-roles-actions-v2.md).
    deliveryNoteReference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correctsDeclarationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDeliveryDeclaration.id", ondelete="RESTRICT"), nullable=True)
    # `fuelProductId`/`declaredVolumeLiters`/`purchaseOrderId`/
    # `reconciledWithId`/`reconciledWithType` ont migré sur
    # `DeliveryDeclarationLine` (refonte « cuve choisie à la livraison, pas à
    # la commande », 2026-09-17, validée scénario par scénario avec le
    # commanditaire — B/C : une livraison peut toucher plusieurs cuves et/ou
    # plusieurs produits en une seule visite, ce qu'une déclaration mono-ligne
    # ne pouvait pas représenter). Cette en-tête ne porte plus que ce qui est
    # commun à toute la visite (station, auteur, date, fournisseur, camion,
    # référence du bon) — jamais un produit/volume/cuve unique.


class DeliveryDeclarationLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une ligne = une cuve réellement remplie durant la visite (refonte
    2026-09-17). `purchaseOrderLineId` NULL = livraison sans commande
    préalable (scénario E, validé explicitement) ; sinon doit référencer une
    ligne de commande du même produit que la cuve visée (contrôlé côté
    service, jamais en base — la cuve détermine le produit, pas de double
    vérité). `correctsLineId` permet une correction CIBLÉE d'une seule ligne
    (scénario I, option validée) : une déclaration corrective ne porte que
    la/les ligne(s) à corriger, chacune pointant la ligne d'origine qu'elle
    remplace — les autres lignes de la déclaration d'origine restent
    valables telles quelles, contrairement à `correctsDeclarationId` qui
    remplace toute la déclaration."""

    __tablename__ = "zyloLiquidDeliveryDeclarationLine"
    __table_args__ = (
        CheckConstraint('"volumeLiters" > 0', name="ck_zlDeliveryDeclarationLine_volumeLiters_positive"),
        {"comment": "Une cuve réellement remplie durant une visite de livraison — une déclaration peut en porter plusieurs."},
    )

    declarationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDeliveryDeclaration.id", ondelete="CASCADE"), nullable=False, index=True)
    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    purchaseOrderLineId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPurchaseOrderLine.id", ondelete="RESTRICT"), nullable=True, index=True)
    volumeLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    correctsLineId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDeliveryDeclarationLine.id", ondelete="RESTRICT"), nullable=True)
    # Rapprochement désormais par ligne (cuve précise), plus par déclaration
    # entière — corrige l'ambiguïté d'une livraison multi-cuves du même
    # produit où l'ancien mécanisme (station+produit+fenêtre de temps)
    # choisissait arbitrairement la cuve la plus proche en temps.
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


# Tracking GPS des camions-citernes — modèles déplacés vers
# `app/location/models.py` (2026-09-15, Phase 2) : GpsIngestCredential,
# GpsDevice, TruckPositionPing, TruckStopEvent, GpsDeviceAssignment,
# TraccarConnection, TruckTrackingLocation, TruckStopReconciliation,
# TruckStopComment, TrackingSettings. Noms de tables Postgres inchangés.
# `TruckOrderAssignment` (rattachement camion<->commande) reste ici, un
# peu plus bas — ce n'est pas du tracking, c'est un lien vers
# `PurchaseOrder`.


class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commande d'approvisionnement (prototype `commandes`, portée station
    comme les entités déclaratives — jamais une colonne organizationId, la
    portée passe par la station, même mécanisme que DeclarationMixin).

    Refonte 2026-09-17 (validée scénario par scénario avec le commanditaire) :
    une commande ne vise plus une cuve précise — la cuve se choisit à la
    LIVRAISON (`DeliveryDeclarationLine.tankId`), jamais à la commande,
    pour permettre qu'une même visite de camion touche plusieurs cuves
    et/ou plusieurs produits (camion compartimenté). Une commande porte
    donc un ou plusieurs produits, chacun sur sa propre `PurchaseOrderLine`
    avec son propre volume commandé et son propre statut de réception.

    `status` (3 états, contrairement aux 2 d'avant la refonte) est agrégé
    depuis les lignes : `open` si aucune ligne n'a reçu de volume,
    `received` si toutes les lignes sont complètes, `partially_received`
    sinon — un gérant voit ainsi dans la liste des commandes qu'un produit
    est déjà arrivé sans devoir ouvrir le détail (ex. Super livré, Gasoil
    encore attendu sur la même commande)."""

    __tablename__ = "zyloLiquidPurchaseOrder"
    __table_args__ = (
        CheckConstraint("status IN ('open','partially_received','received')", name="ck_zlPurchaseOrder_status"),
        {"comment": "Commande d'approvisionnement multi-produits — statut agrégé depuis PurchaseOrderLine."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplierId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSupplier.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    orderReference: Mapped[str] = mapped_column(String(100), nullable=False)
    orderedAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    expectedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")


class PurchaseOrderLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une ligne = un produit commandé, avec son propre volume et son propre
    statut de réception — une commande multi-produits (camion compartimenté,
    scénario C) porte autant de lignes que de produits distincts."""

    __tablename__ = "zyloLiquidPurchaseOrderLine"
    __table_args__ = (
        CheckConstraint("status IN ('open','partially_received','received')", name="ck_zlPurchaseOrderLine_status"),
        CheckConstraint('"orderedVolumeLiters" > 0', name="ck_zlPurchaseOrderLine_orderedVolumeLiters_positive"),
        {"comment": "Un produit commandé — le statut de la commande est agrégé depuis ses lignes."},
    )

    purchaseOrderId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPurchaseOrder.id", ondelete="CASCADE"), nullable=False, index=True)
    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False, index=True)
    orderedVolumeLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")


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
    # Début de shift — optionnel (nullable) : les ventes créées avant
    # l'ajout de ce champ (2026-09-25) n'en ont pas, et une déclaration
    # groupée peut aussi provenir d'un import où cette donnée manque
    # (jamais une valeur inventée à sa place). `eventAt` reste la fin de
    # shift, seule donnée obligatoire jusqu'ici — inchangé.
    shiftStart: Mapped[datetime | None] = mapped_column(nullable=True)
    eventAt: Mapped[datetime] = mapped_column(nullable=False, index=True)
    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False)
    quantityLiters: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    priceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    paymentMethod: Mapped[str] = mapped_column(String(20), nullable=False)
    commercialAccountId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=True)
    vehicleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidVehicle.id", ondelete="RESTRICT"), nullable=True)
    driverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDriver.id", ondelete="RESTRICT"), nullable=True)
    pumpId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPump.id", ondelete="RESTRICT"), nullable=True, index=True)
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


# Modèle documentaire (Document/DocumentLink) — déplacé vers
# `app/files/models.py` (2026-09-15, Phase 1 de la migration monolithe
# modulaire). Noms de tables Postgres inchangés, aucune migration de
# données pour ce déplacement.


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
        CheckConstraint("\"stockQuantity\" >= 0", name="ck_zlSellableProduct_stock_non_negative"),
        {"comment": "Produit vendable non-carburant (boutique) — stock simple (quantité par produit×station, sans journal de mouvements détaillé, Phase 4 mission Boutique)."},
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
    stockQuantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    lowStockThreshold: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Référence de stockage (même mécanisme que User.photoStorageReference) —
    # jamais d'URL directe stockée, toujours résolue à la volée via
    # get_storage_backend().get_download_url(...) pour bénéficier de la
    # signature/expiration déjà en place pour les autres médias de l'app.
    imageStorageReference: Mapped[str | None] = mapped_column(Text, nullable=True)


class SellableProductPrice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historique des prix des produits boutique — même principe de
    résolution à 2 niveaux (station précise / défaut réseau) que
    `PriceHistory` pour le carburant (Point 2 §7.3-7.6), demandé
    explicitement pour rendre la tarification boutique réaliste par station
    plutôt qu'un prix unique figé sur `SellableProduct.unitPriceAmount`.
    `SellableProduct.unitPriceAmount` reste un prix de repli/affichage par
    défaut quand aucune ligne n'existe encore ici (catalogue fraîchement
    créé, avant toute tarification explicite par station)."""

    __tablename__ = "zyloLiquidSellableProductPrice"
    __table_args__ = (
        UniqueConstraint(
            "stationId", "sellableProductId", "effectiveFrom", name="uq_zlSellableProductPrice_station_product_effectiveFrom"
        ),
        # Même garde-fou que uq_zlPriceHistory_networkDefault_product_effectiveFrom
        # (PostgreSQL ne considère jamais deux NULL comme égaux) : sans cet
        # index partiel, plusieurs prix réseau par défaut pourraient coexister
        # pour la même devise/date pour un même produit.
        Index(
            "uq_zlSellableProductPrice_networkDefault_product_effectiveFrom",
            "sellableProductId", "currencyId", "effectiveFrom",
            unique=True,
            postgresql_where='"stationId" IS NULL',
        ),
        CheckConstraint('"priceAmount" > 0', name="ck_zlSellableProductPrice_priceAmount_positive"),
        {"comment": "Historique des prix des produits boutique — changement réel = insertion, correction = UPDATE ciblé."},
    )

    stationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    sellableProductId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidSellableProduct.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False)
    priceAmount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    costAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    effectiveFrom: Mapped[datetime] = mapped_column(nullable=False, index=True)
    changeReason: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)


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
        # A4 (D14) : N° d'employé unique par station si renseigné.
        Index(
            "uq_zlStationStaffProfile_station_employeeNumber", "assignedStationId", "employeeNumber", unique=True,
            postgresql_where=text('"employeeNumber" IS NOT NULL AND "assignedStationId" IS NOT NULL'),
        ),
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


# GpsDeviceAssignment/TraccarConnection/TruckTrackingLocation/
# TruckStopReconciliation/TruckStopComment — déplacés vers
# `app/location/models.py` (2026-09-15, Phase 2).


class TruckOrderAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rattachement optionnel camion<->commande — plusieurs-à-plusieurs
    (plusieurs camions sur une commande, un camion sur plusieurs
    commandes), jamais obligatoire. Portée par la commande (comme
    `PurchaseOrder` lui-même), pas par organisation."""

    __tablename__ = "zyloLiquidTruckOrderAssignment"
    __table_args__ = (
        UniqueConstraint("truckId", "purchaseOrderId", name="uq_zlTruckOrderAssignment_truck_order"),
        {"comment": "Lien plusieurs-à-plusieurs camion<->commande d'approvisionnement, toujours optionnel."},
    )

    truckId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="CASCADE"), nullable=False, index=True)
    purchaseOrderId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPurchaseOrder.id", ondelete="CASCADE"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


# TrackingSettings — déplacé vers `app/location/models.py` (2026-09-15,
# Phase 2).


class ShiftDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Modèle de tour d'une station (« Matin 06:00 → 14:00 ») — scénario A9.
    Ce n'est PAS un tour réel du jour (planifié/ouvert/fermé, vus en A5/B3) :
    seulement la définition réutilisable. Jamais supprimé, seulement
    désactivé (`active`), pour garder l'historique — même convention que
    `Pump`/`Tank`. Heures en heure locale de la station, sans conversion."""

    __tablename__ = "zyloLiquidShiftDefinition"
    __table_args__ = (
        UniqueConstraint("stationId", "shiftNumber", name="uq_zlShiftDefinition_station_number", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("stationId", "name", name="uq_zlShiftDefinition_station_name", deferrable=True, initially="DEFERRED"),
        CheckConstraint('"shiftNumber" > 0', name="ck_zlShiftDefinition_shiftNumber_positive"),
        {"comment": "Modèle de tour (période de travail d'une équipe) d'une station ; référentiel, sans planning."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shiftNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Numéro d'ordre du tour, unique par station (ordre d'affichage).")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Nom du tour, unique par station.")
    # Texte « HH:MM » (pas un type TIME) : le contrat d'API l'échange tel quel
    # et un tour peut passer minuit (fin <= début), ce que la durée calculée gère.
    startTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Heure de début locale, format HH:MM.")
    endTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Heure de fin locale, format HH:MM ; fin <= début = passe minuit (début = fin = 24 h).")
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ShiftOccurrence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tour du jour planifié (scénario A5) : un modèle de tour (`ShiftDefinition`)
    placé à une date précise d'une station. Les horaires et le nom sont COPIÉS du
    modèle à la création et ne sont jamais resynchronisés : modifier le modèle
    plus tard n'altère pas un tour déjà planifié. A5 ne crée et ne modifie que le
    statut `planned` ; `opened`/`closed`/`validated` (et leurs horodatages) sont
    prévus pour B3 et la suite, sans logique ici. Heures locales de la station,
    sans conversion de fuseau (même convention qu'A9)."""

    __tablename__ = "zyloLiquidShiftOccurrence"
    __table_args__ = (
        UniqueConstraint("stationId", "shiftDate", "shiftDefinitionId", name="uq_zlShiftOccurrence_station_date_shift"),
        CheckConstraint("status IN ('planned','opened','closed','validated')", name="ck_zlShiftOccurrence_status"),
        Index("ix_zlShiftOccurrence_station_date", "stationId", "shiftDate"),
        # B3 : un seul tour ouvert par station (y compris un tour de 24 h).
        Index("uq_zlShiftOccurrence_station_opened", "stationId", unique=True, postgresql_where=text("status = 'opened'")),
        {"comment": "Tour du jour planifié d'une station (date + modèle de tour), horaires copiés du modèle ; cycle planned -> opened -> closed -> validated."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shiftDefinitionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftDefinition.id", ondelete="RESTRICT"), nullable=False, index=True,
        comment="Modèle d'origine ; référence conservée, mais les champs copiés ci-dessous font foi pour l'occurrence.",
    )
    shiftDate: Mapped[date] = mapped_column(Date, nullable=False, comment="Date locale de DÉBUT du tour (un tour de nuit du lundi appartient au lundi).")
    shiftNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Copie du numéro d'ordre du modèle à la planification.")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Copie du nom du modèle à la planification.")
    startTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Copie de l'heure de début locale (HH:MM).")
    endTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Copie de l'heure de fin locale (HH:MM) ; fin <= début = passe minuit.")
    # Heure locale de la station : DateTime SANS fuseau volontairement (pas de conversion, A9/Q7).
    startsAt: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, comment="Début réel prévu (date + heure copiée), heure locale station.")
    endsAt: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, comment="Fin réelle prévue (lendemain si le tour passe minuit), heure locale station ; sert au contrôle de chevauchement.")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="planned", comment="planned (géré par A5) | opened | closed | validated (B3 et suite).")
    # Prévus pour les statuts suivants, jamais renseignés par A5.
    openedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Ouverture réelle du tour (B3), non géré par A5.")
    closedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Clôture réelle du tour, non gérée par A5.")
    validatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Validation du tour, non gérée par A5.")
    # B3 : ouverture du tour.
    openedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Utilisateur qui a ouvert le tour (B3) ; peut être le gérant.")
    offPlanning: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Vrai si l'occurrence a été créée à l'ouverture, faute de planning (B3).")


class ShiftAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Affectation d'une personne à un tour planifié (scénario A5) : rôle dans
    le tour (responsable de tour, chef d'équipe, pompiste) et pompe optionnelle
    (pompiste seulement). Supprimée avec son occurrence."""

    __tablename__ = "zyloLiquidShiftAssignment"
    __table_args__ = (
        # Un pompiste peut tenir PLUSIEURS pompes dans un même tour (SOCADA : 6 pompistes
        # pour 14 pompes) : pas d'unicité (occurrence, personne) ; seulement une ligne
        # « sans pompe » par personne (les doublons de pompe sont déjà exclus par
        # l'index sur (occurrence, pompe)). « Un seul rôle par personne et par tour »
        # est contrôlé par le service.
        Index("uq_zlShiftAssignment_occurrence_user_nopump", "occurrenceId", "userId", unique=True, postgresql_where=text('"pumpId" IS NULL')),
        CheckConstraint("\"shiftRole\" IN ('shift_manager','team_lead','pump_attendant')", name="ck_zlShiftAssignment_shiftRole"),
        CheckConstraint("\"pumpId\" IS NULL OR \"shiftRole\" = 'pump_attendant'", name="ck_zlShiftAssignment_pump_only_attendant"),
        # Une pompe n'a qu'un pompiste par tour (règle par défaut, PC-18).
        Index("uq_zlShiftAssignment_occurrence_pump", "occurrenceId", "pumpId", unique=True, postgresql_where=text('"pumpId" IS NOT NULL')),
        # Un seul responsable de tour par occurrence.
        Index("uq_zlShiftAssignment_occurrence_manager", "occurrenceId", unique=True, postgresql_where=text("\"shiftRole\" = 'shift_manager'")),
        {"comment": "Affectation d'une personne à un tour planifié : rôle dans le tour et pompe optionnelle (pompiste)."},
    )

    occurrenceId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftOccurrence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    shiftRole: Mapped[str] = mapped_column(String(20), nullable=False, comment="shift_manager | team_lead | pump_attendant.")
    pumpId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidPump.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Pompe tenue (pompiste seulement) ; NULL = placé sans pompe précise (renfort).",
    )


class ShiftAttendanceSheet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Feuille de pointage d'un tour (scénario B1) : UNE par occurrence, créée au
    PREMIER enregistrement seulement (avant cela, la lecture renvoie des lignes
    virtuelles pré-remplies depuis le planning, rien n'est stocké). L'enregistrement
    par l'utilisateur authentifié vaut signature (auteur + horodatage serveur) :
    le premier enregistrement n'est jamais modifié, le dernier est rafraîchi.
    `version` sert au verrou optimiste (409 `attendance_changed`). Le verrou
    `locked` (tour validé, E1) est calculé à la lecture depuis l'occurrence."""

    __tablename__ = "zyloLiquidShiftAttendanceSheet"
    __table_args__ = (
        UniqueConstraint("occurrenceId", name="uq_zlShiftAttendanceSheet_occurrence"),
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlShiftAttendanceSheet_lifecycleStatus"),
        {"comment": "Feuille de pointage d'un tour (une par occurrence) : signature du dernier enregistrement et version pour le verrou optimiste."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurrenceId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftOccurrence.id", ondelete="RESTRICT"), nullable=False,
        comment="Tour (occurrence A5) pointé ; une seule feuille par tour.",
    )
    version: Mapped[int] = mapped_column(nullable=False, server_default="1", comment="Incrémentée à chaque enregistrement ; verrou optimiste.")
    firstSignedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Auteur du premier enregistrement (jamais modifié).")
    firstSignedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur du premier enregistrement (jamais modifié).")
    lastSignedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Signature : auteur du dernier enregistrement.")
    lastSignedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Signature : horodatage serveur du dernier enregistrement.")
    lifecycleStatus: Mapped[str] = mapped_column(String(10), nullable=False, server_default="declared", comment="declared | locked (tour validé, E1).")


class ShiftAttendanceLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de pointage (scénario B1) : une par personne planifiée (`planned`),
    par remplaçant lié à un absent (`replacement`) ou par personne présente hors
    planning (`unplanned`). Le PRÉVU reste lu via `plannedAssignmentId` (rôle,
    pompes), jamais recopié ni modifié ; le RÉEL (statut, heures) vit ici. Le
    statut initial est `pending` (« à pointer »), jamais `present` par défaut.
    Heures en heure locale de la station, sans fuseau (même convention qu'A5/A9)."""

    __tablename__ = "zyloLiquidShiftAttendanceLine"
    __table_args__ = (
        UniqueConstraint("sheetId", "plannedAssignmentId", name="uq_zlShiftAttendanceLine_sheet_assignment"),
        UniqueConstraint("replacesLineId", name="uq_zlShiftAttendanceLine_replaces"),
        Index("uq_zlShiftAttendanceLine_sheet_person", "sheetId", "personUserId", unique=True, postgresql_where=text('"personUserId" IS NOT NULL')),
        CheckConstraint("\"lineKind\" IN ('planned','replacement','unplanned')", name="ck_zlShiftAttendanceLine_lineKind"),
        CheckConstraint("status IN ('pending','present','late','absent_justified','absent_unjustified')", name="ck_zlShiftAttendanceLine_status"),
        CheckConstraint("\"lineKind\" <> 'replacement' OR \"replacesLineId\" IS NOT NULL", name="ck_zlShiftAttendanceLine_replacement_needs_target"),
        CheckConstraint("\"replacesLineId\" IS NULL OR \"lineKind\" = 'replacement'", name="ck_zlShiftAttendanceLine_target_only_replacement"),
        CheckConstraint("\"lineKind\" <> 'planned' OR \"plannedAssignmentId\" IS NOT NULL", name="ck_zlShiftAttendanceLine_planned_needs_assignment"),
        CheckConstraint("\"plannedAssignmentId\" IS NULL OR \"lineKind\" = 'planned'", name="ck_zlShiftAttendanceLine_assignment_only_planned"),
        CheckConstraint("status IN ('present','late') OR (\"arrivedAt\" IS NULL AND \"departedAt\" IS NULL)", name="ck_zlShiftAttendanceLine_no_times_if_absent"),
        CheckConstraint("(\"personUserId\" IS NULL) <> (\"externalName\" IS NULL)", name="ck_zlShiftAttendanceLine_person_xor_external"),
        CheckConstraint("\"shiftRole\" IN ('shift_manager','team_lead','pump_attendant')", name="ck_zlShiftAttendanceLine_shiftRole"),
        {"comment": "Ligne de pointage d'un tour : personne planifiée, remplaçant lié ou personne hors planning ; prévu (affectation A5) et réel (statut, heures) conservés côte à côte."},
    )

    sheetId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftAttendanceSheet.id", ondelete="CASCADE"), nullable=False, index=True)
    lineKind: Mapped[str] = mapped_column(String(12), nullable=False, comment="planned | replacement | unplanned (déduit, jamais saisi).")
    plannedAssignmentId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftAssignment.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Affectation A5 représentant la personne prévue (kind planned) ; le prévu se lit via elle, jamais recopié.",
    )
    replacesLineId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftAttendanceLine.id", ondelete="RESTRICT"), nullable=True,
        comment="Ligne `planned` absente remplacée par cette ligne (kind replacement) ; un seul remplaçant par absent.",
    )
    personUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True, comment="Personne pointée ; NULL pour un remplaçant externe sans compte (nom libre).")
    externalName: Mapped[str | None] = mapped_column(String(120), nullable=True, comment="Nom libre d'un remplaçant externe sans compte (jamais affectable à une pompe sans compte).")
    shiftRole: Mapped[str] = mapped_column(String(20), nullable=False, comment="Rôle réel dans le tour : planned = rôle de l'affectation ; replacement = rôle de la ligne remplacée ; unplanned = poste de la personne.")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="pending (à pointer, défaut) | present | late | absent_justified | absent_unjustified.")
    arrivedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, comment="Arrivée réelle (heure locale station, résolue depuis HH:MM) ; obligatoire si present/late, interdite sinon.")
    departedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, comment="Départ réel (heure locale station) ; facultatif, postérieur à l'arrivée.")
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Motif (obligatoire pour absent_justified, facultatif pour absent_unjustified et late, interdit sinon).")
    note: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Note libre facultative.")
    declaredByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Auteur de la dernière modification de cette ligne.")
    declaredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la dernière modification de cette ligne.")
    changeReason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Raison d'une correction faite alors que le tour est clos.")


class ShiftHandover(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Passation d'un tour (scénario B2) : ce que le tour SORTANT laisse au
    suivant. Ancrée à l'occurrence sortante (le tour suivant peut ne pas exister),
    créée au premier enregistrement. Signature = dernier enregistrement par
    l'utilisateur authentifié ; prise de connaissance = trace de lecture du RT
    entrant (pas un accord sur le contenu) et non bloquante."""

    __tablename__ = "zyloLiquidShiftHandover"
    __table_args__ = (
        UniqueConstraint("occurrenceId", name="uq_zlShiftHandover_occurrence"),
        CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlShiftHandover_lifecycleStatus"),
        {"comment": "Passation d'un tour sortant au suivant (une par occurrence) : signature, case « rien à signaler », prise de connaissance."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurrenceId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftOccurrence.id", ondelete="RESTRICT"), nullable=False,
        comment="Occurrence SORTANTE : la passation est ce que ce tour laisse au suivant.",
    )
    nothingToReport: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="« Rien à signaler » explicite : vrai exige zéro ligne, faux exige au moins une ligne.")
    version: Mapped[int] = mapped_column(nullable=False, server_default="1", comment="Incrémentée à chaque enregistrement ; verrou optimiste (409 handover_changed).")
    firstSignedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Auteur du premier enregistrement (jamais modifié).")
    firstSignedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur du premier enregistrement (jamais modifié).")
    lastSignedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Signature : auteur du dernier enregistrement.")
    lastSignedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Signature : horodatage serveur du dernier enregistrement.")
    receivedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Personne ayant pris connaissance (dernière prise) ; NULL = pas encore reçue.")
    receivedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage serveur de la dernière prise de connaissance ; la première reste dans l'audit.")
    receivingOccurrenceId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftOccurrence.id", ondelete="SET NULL"), nullable=True,
        comment="Occurrence du tour suivant au moment de la prise de connaissance ; NULL si aucun tour suivant.",
    )
    lifecycleStatus: Mapped[str] = mapped_column(String(10), nullable=False, server_default="declared", comment="declared | locked (tour sortant validé, E1).")


class ShiftHandoverItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de passation (scénario B2) : consigne (`instruction`), anomalie en
    cours (`open_issue`, persiste au niveau STATION jusqu'à être réglée) ou
    information (`info`). Texte écrit par une personne : jamais généré par le
    système, jamais interprété. Une consigne du gérant est une ligne `instruction`
    dont `authorRole` = `station_admin` (pas de table séparée)."""

    __tablename__ = "zyloLiquidShiftHandoverItem"
    __table_args__ = (
        CheckConstraint("kind IN ('instruction','open_issue','info')", name="ck_zlShiftHandoverItem_kind"),
        CheckConstraint("category IN ('pump','tank','delivery','price_credit','safety','staff','customer','report_feedback','other')", name="ck_zlShiftHandoverItem_category"),
        CheckConstraint("importance IN ('normal','high')", name="ck_zlShiftHandoverItem_importance"),
        CheckConstraint("\"pumpId\" IS NULL OR category = 'pump'", name="ck_zlShiftHandoverItem_pump_only_category_pump"),
        CheckConstraint("\"tankId\" IS NULL OR category = 'tank'", name="ck_zlShiftHandoverItem_tank_only_category_tank"),
        CheckConstraint("(status IS NOT NULL) = (kind = 'open_issue')", name="ck_zlShiftHandoverItem_status_iff_open_issue"),
        CheckConstraint("status IS NULL OR status IN ('open','closed')", name="ck_zlShiftHandoverItem_status"),
        CheckConstraint("\"closedAt\" IS NULL OR status = 'closed'", name="ck_zlShiftHandoverItem_closed_needs_status"),
        CheckConstraint(
            "status IS DISTINCT FROM 'closed' OR (\"closedAt\" IS NOT NULL AND \"closedByUserId\" IS NOT NULL AND resolution IS NOT NULL)",
            name="ck_zlShiftHandoverItem_closed_needs_resolution",
        ),
        Index("ix_zlShiftHandoverItem_open_issues", "handoverId", postgresql_where=text("status = 'open'")),
        {"comment": "Ligne de passation : consigne, anomalie en cours (niveau station jusqu'à réglée) ou information, écrite par une personne."},
    )

    handoverId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftHandover.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="Ordre de saisie dans le tableau (affichage).")
    kind: Mapped[str] = mapped_column(String(12), nullable=False, comment="instruction (consigne) | open_issue (anomalie en cours) | info (information).")
    category: Mapped[str] = mapped_column(String(20), nullable=False, comment="pump | tank | delivery | price_credit | safety | staff | customer | report_feedback | other.")
    pumpId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPump.id", ondelete="RESTRICT"), nullable=True, index=True, comment="Pompe concernée (catégorie pump) ; une pompe désactivée reste choisissable.")
    tankId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=True, index=True, comment="Cuve concernée (catégorie tank).")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="Texte libre factuel (3 à 1000 caractères), jamais interprété par le système.")
    importance: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal", comment="normal | high.")
    status: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="open_issue seulement : open puis closed ; NULL pour les autres types.")
    closedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Auteur du règlement de l'anomalie.")
    closedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage serveur du règlement de l'anomalie.")
    resolution: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="Comment l'anomalie a été réglée (obligatoire à la clôture).")
    authorUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Auteur de la ligne.")
    authorRole: Mapped[str] = mapped_column(String(30), nullable=False, comment="Rôle de l'auteur à l'écriture : station_admin (gérant/direction) ou shift_manager ; mémorisé pour afficher « consigne du gérant ».")
    declaredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement de la ligne.")
    addedAfterReceipt: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Vrai si ajoutée après la prise de connaissance (affichée « complément »).")
    changeReason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Raison d'une correction faite alors que la passation est déjà reçue.")


class ShiftReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rapport de tour (scénario B3) : UN par occurrence, créé à l'ouverture du tour
    dans la même transaction que le passage `planned -> opened`. Station, journée et
    tour sont COPIÉS de l'occurrence (jamais resynchronisés). Le RT prévu (planning)
    et le RT réel (en-tête) sont conservés côte à côte (PC-40). D1 à D8 ajouteront
    leurs colonnes ; B3 ne crée que celles dont il a besoin. Le statut du rapport
    suit celui de l'occurrence."""

    __tablename__ = "zyloLiquidShiftReport"
    __table_args__ = (
        UniqueConstraint("occurrenceId", name="uq_zlShiftReport_occurrence"),
        Index("ix_zlShiftReport_station_date", "stationId", "shiftDate"),
        CheckConstraint("\"closingPhase\" IN ('open','ready_to_close')", name="ck_zlShiftReport_closingPhase"),
        {"comment": "Rapport de tour d'une station (un par occurrence), créé à l'ouverture du tour : en-tête, responsable de tour prévu et réel."},
    )

    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    occurrenceId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftOccurrence.id", ondelete="RESTRICT"), nullable=False, comment="Tour (occurrence A5) dont ce rapport est le rapport ; un seul rapport par tour."
    )
    shiftDate: Mapped[date] = mapped_column(Date, nullable=False, comment="Journée du rapport = date de début du tour (copie de l'occurrence).")
    shiftNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Copie du numéro du tour.")
    shiftName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Copie du nom du tour.")
    startTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Copie de l'heure de début (HH:MM).")
    endTime: Mapped[str] = mapped_column(String(5), nullable=False, comment="Copie de l'heure de fin (HH:MM).")
    responsibleUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Responsable de tour RÉEL du rapport (en-tête).")
    responsiblePhone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="Téléphone du responsable copié du compte ou saisi à l'ouverture ; jamais inventé.")
    plannedResponsibleUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Responsable de tour PRÉVU au planning (A5) ; nul si aucun (trace prévu vs réel).")
    openedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Utilisateur qui a ouvert le tour (peut être le gérant).")
    openedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'ouverture (UTC).")
    # --- Colonnes ajoutées par D1 (index de fermeture des pompes) ---
    closingVersion: Mapped[int] = mapped_column(nullable=False, server_default="0", comment="Version du bloc « fermeture des pompes » (D1) : 0 tant que rien n'est enregistré, +1 à chaque enregistrement ; verrou optimiste (409 closing_version_changed) et base de l'état « à recalculer » de D2/D3.")
    closingPhase: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open", comment="open (en cours) | ready_to_close (index de fermeture enregistrés, D1). La fermeture définitive du tour (statut `closed` de l'occurrence) reste D7 : cette phase ne ferme rien.")
    closingLastRecordedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D1 (nul tant que rien n'est enregistré).")
    closingLastRecordedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Auteur du dernier enregistrement D1 (RT ou gérant à sa place).")
    # --- Colonnes ajoutées par D3 (caisse par pompiste) ---
    cashVersion: Mapped[int] = mapped_column(nullable=False, server_default="0", comment="Version du bloc « caisse par pompiste » (D3) : 0 tant que rien n'est enregistré, +1 à chaque enregistrement ; verrou optimiste (409 cash_version_changed).")
    cashLastRecordedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D3 (nul tant que rien n'est enregistré).")
    cashLastRecordedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Auteur du dernier enregistrement D3 (RT ou gérant à sa place) ; sert au message de conflit de version.")


class ShiftReportPumpLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de pompe d'un rapport (scénario B3) : UNE par pompe ACTIVE à l'ouverture
    (ou ajoutée explicitement en cours de tour). Numéro, nom, cuve et produit sont un
    INSTANTANÉ : renommer le produit ou changer la cuve plus tard n'altère pas le
    rapport. `openingSource` garde l'origine de l'index pour que D1 sache quand une
    exception (compteur remplacé/remis à zéro) est légitime. Les colonnes `closing*`
    sont réservées à D1 (aucun code B3 ne les écrit) : elles alimentent le report
    vers le tour suivant (`get_last_closing_for_pump`)."""

    __tablename__ = "zyloLiquidShiftReportPumpLine"
    __table_args__ = (
        UniqueConstraint("reportId", "pumpId", name="uq_zlShiftReportPumpLine_report_pump"),
        CheckConstraint("\"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportPumpLine_openingSource"),
        CheckConstraint("\"openingIndex\" >= 0", name="ck_zlShiftReportPumpLine_openingIndex_positive"),
        CheckConstraint("\"openingSource\" = 'continuity_break' OR (\"continuityBreakReason\" IS NULL AND \"continuityBreakNote\" IS NULL)", name="ck_zlShiftReportPumpLine_break_only_on_break"),
        CheckConstraint("\"counterEvent\" IN ('none','rollover','replaced')", name="ck_zlShiftReportPumpLine_counterEvent"),
        CheckConstraint("(\"exitsLiters\" IS NULL OR \"exitsLiters\" >= 0) AND (\"tankReturnLiters\" IS NULL OR \"tankReturnLiters\" >= 0)", name="ck_zlShiftReportPumpLine_exits_nonneg"),
        {"comment": "Ligne de pompe d'un rapport de tour : index d'ouverture (reporté, initial ou écart déclaré) et instantané des libellés de la pompe."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    pumpId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPump.id", ondelete="RESTRICT"), nullable=False, index=True)
    pumpNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Instantané du numéro de la pompe à l'ouverture.")
    pumpName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Instantané du nom généré de la pompe.")
    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, comment="Instantané de la cuve de la pompe à l'ouverture.")
    fuelProductName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Instantané du produit (via la cuve).")
    openingIndex: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Index d'ouverture ; comparé en décimal exact, jamais en flottant.")
    openingSource: Mapped[str] = mapped_column(String(20), nullable=False, comment="carried (reporté de la fermeture précédente) | initial (premier tour de la pompe, saisi) | continuity_break (écart déclaré avec motif).")
    carriedIndex: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Fermeture précédente que le serveur avait calculée (écart = openingIndex - carriedIndex) ; nul si initial.")
    previousLineId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="SET NULL"), nullable=True, comment="Ligne du tour précédent dont la fermeture a été reportée (traçabilité) ; nul si initial."
    )
    continuityBreakReason: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="meter_replaced | meter_reset | carry_error | other (écart de continuité seulement).")
    continuityBreakNote: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Précision de l'écart de continuité (10 caractères minimum).")
    addedDuringShift: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Vrai si la ligne a été ajoutée explicitement après l'ouverture (« Ajouter une pompe au tour »).")
    lockedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Verrouillage de l'ouverture à la création ; correction possible seulement tant que le tour est ouvert (initial/écart).")
    closingIndex: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Index de fermeture : RÉSERVÉ à D1 (non écrit par B3) ; sert de source au report du tour suivant.")
    # --- Colonnes ajoutées par D1 (`closingIndex` ci-dessus a été créée par B3 et est écrite par D1) ---
    closingReadWithUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Personne avec qui l'index de fermeture a été lu à deux (pompiste de la pompe ou chef d'équipe) ; déclaratif, jamais une signature.")
    closingReadAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage SERVEUR de l'enregistrement de l'index de fermeture (≠ heure réelle de lecture, jamais prétendu).")
    closingRecordedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Qui a saisi l'index de fermeture (RT ou gérant à sa place).")
    exitsLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True, comment="Sorties : litres passés dans la pompe sans être vendus (test, étalonnage) ; nul = non déclaré = 0 (méthode PC-04 provisoire).")
    tankReturnLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True, comment="Retours en cuve : litres remis en cuve (≤ sorties) ; n'agissent que sur le stock (D2), jamais sur les litres vendus (PC-04).")
    exitsNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Observation des sorties ; obligatoire si les sorties sont > 0.")
    counterEvent: Mapped[str] = mapped_column(String(10), nullable=False, server_default="none", comment="none | rollover (compteur remis à zéro après 999 999,99) | replaced (compteur remplacé).")
    counterEventNote: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Précision de l'événement compteur (10 caractères minimum) ; obligatoire si counterEvent ≠ none.")
    replacedOldFinalIndex: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Dernier index de l'ancien compteur (compteur remplacé seulement).")
    replacedNewStartIndex: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Index de départ du nouveau compteur (compteur remplacé seulement).")
    zeroSaleConfirmed: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Vrai si le RT a confirmé « pompe sans vente » (fermeture = ouverture) pour cette ligne.")
    soldLiters: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Litres vendus CALCULÉS par le serveur : (fermeture - ouverture) - sorties (méthode PC-04 provisoire, formules spéciales si événement compteur) ; nul tant que l'index de fermeture n'est pas saisi.")
    unitPriceAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True, comment="Prix unitaire en vigueur à l'OUVERTURE du tour, COPIÉ à l'enregistrement (changer le prix plus tard n'altère pas le rapport) ; nul = prix non disponible (jamais un prix inventé).")
    unitPriceCurrencyId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=True, comment="Devise du prix copié.")
    unitPriceEffectiveFrom: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, comment="Date d'effet du prix retenu (traçabilité, avertissement « prix modifié pendant le tour »).")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Montant de la ligne = litres vendus × prix copié, arrondi à 2 décimales ; nul si le prix est non disponible.")


class ShiftReportPumpLineCorrection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rature d'une valeur déjà enregistrée d'une ligne de pompe (scénario D1) : UNE ligne par champ modifié
    (`closingIndex`, `exitsLiters`, `tankReturnLiters`). L'ancienne valeur est CONSERVÉE (jamais d'écrasement
    silencieux), avec motif et « paraphé par » obligatoires (cahier §5.3 : « une rature est paraphée »)."""

    __tablename__ = "zyloLiquidShiftReportPumpLineCorrection"
    __table_args__ = (
        CheckConstraint("\"field\" IN ('closingIndex','exitsLiters','tankReturnLiters')", name="ck_zlShiftReportPumpLineCorrection_field"),
        CheckConstraint("\"reasonCode\" IN ('read_error','digits_swapped','decimal_forgotten','read_before_end','other')", name="ck_zlShiftReportPumpLineCorrection_reason"),
        {"comment": "Historique des ratures d'une ligne de pompe du rapport (index de fermeture, sorties, retours) : ancienne valeur conservée, motif, paraphé par."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    pumpLineId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Ligne de pompe corrigée.")
    field: Mapped[str] = mapped_column(String(20), nullable=False, comment="Champ modifié : closingIndex | exitsLiters | tankReturnLiters.")
    oldValue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Valeur avant la correction (conservée, jamais écrasée) ; nulle si le champ n'était pas déclaré.")
    newValue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Valeur après la correction ; nulle si le champ est vidé.")
    reasonCode: Mapped[str] = mapped_column(String(20), nullable=False, comment="Motif de la liste : read_error | digits_swapped | decimal_forgotten | read_before_end | other.")
    reasonNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »).")
    initialedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif, pompiste ou chef d'équipe).")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la correction (RT ou gérant).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction.")
    closingVersion: Mapped[int] = mapped_column(nullable=False, comment="Version du bloc « fermeture des pompes » produite par cette correction.")


class ShiftReportTankLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de cuve d'un rapport (scénario B3) : UNE par cuve ACTIVE à l'ouverture.
    Stock d'ouverture en LITRES (hauteur et table de jaugeage hors B3, PC-35), reporté
    du stock réel de fermeture du tour précédent (D2) ou saisi (`initial`). La colonne
    `closingRealStockLiters` est RÉSERVÉE à D2 (aucun code B3 ne l'écrit)."""

    __tablename__ = "zyloLiquidShiftReportTankLine"
    __table_args__ = (
        UniqueConstraint("reportId", "tankId", name="uq_zlShiftReportTankLine_report_tank"),
        CheckConstraint("\"openingStockSource\" IN ('previous_real_stock','initial')", name="ck_zlShiftReportTankLine_openingStockSource"),
        CheckConstraint("\"openingStockLiters\" >= 0", name="ck_zlShiftReportTankLine_openingStock_positive"),
        {"comment": "Ligne de cuve d'un rapport de tour : stock d'ouverture en litres (reporté ou initial) et instantané des libellés de la cuve."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    tankId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="RESTRICT"), nullable=False, index=True)
    tankNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Instantané du numéro de la cuve.")
    tankName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Instantané du libellé de la cuve.")
    fuelProductName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Instantané du produit de la cuve.")
    capacityLiters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="Instantané de la capacité de la cuve (litres).")
    openingStockLiters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="Stock d'ouverture en litres, entre 0 et la capacité.")
    openingStockSource: Mapped[str] = mapped_column(String(20), nullable=False, comment="previous_real_stock (stock réel de fermeture du tour précédent, D2) | initial (saisi).")
    previousTankLineId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportTankLine.id", ondelete="SET NULL"), nullable=True, comment="Ligne de cuve du tour précédent reportée ; nulle si initial."
    )
    closingRealStockLiters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True, comment="Stock réel de fermeture en litres : RÉSERVÉ à D2 (non écrit par B3) ; source du report du tour suivant.")


class ShiftPumpAssignmentSheet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Confirmation de l'affectation de départ des pompistes d'un rapport de tour
    (scénario B4) : UNE par rapport, créée à la confirmation (« Enregistrer tout »)
    uniquement ; avant cela, la lecture renvoie un brouillon calculé depuis le
    planning A5, rien n'est stocké. Sa présence = verrou de l'affectation de départ
    (tout changement ultérieur passe par B5). `version` sert au verrou optimiste
    (409 `assignment_changed`) ; B5 l'incrémente à chaque mouvement de personnel."""

    __tablename__ = "zyloLiquidShiftPumpAssignmentSheet"
    __table_args__ = (
        UniqueConstraint("reportId", name="uq_zlShiftPumpAssignmentSheet_report"),
        {"comment": "Confirmation (verrou) de l'affectation de départ des pompistes d'un rapport de tour ; une par rapport."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False,
        comment="Rapport de tour (B3) dont l'affectation de départ est confirmée.",
    )
    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1", comment="Incrémentée à chaque modification de l'affectation (B4 : 1 à la confirmation ; B5 ensuite) ; verrou optimiste.")
    plannedDeciderUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True,
        comment="Chef d'équipe PRÉVU au planning (A5) à la confirmation ; figé, jamais écrasé.",
    )
    decidedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True,
        comment="Chef d'équipe décideur (information, non authentifiante : il décide oralement, le RT saisit).",
    )
    confirmedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la confirmation (verrou).")
    confirmedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Utilisateur qui a saisi et confirmé (RT ou gérant).")


class ShiftPumpAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Segment d'affectation d'une pompe à un pompiste pendant un tour (scénario B4).
    Chronologie par pompe : B4 ne crée que les segments de départ (`kind = start`) ;
    B5 clôt un segment (`endsAt`) et en ouvre un autre sans jamais réécrire
    l'original. PRÉVU (`plannedUserId`, copie de l'affectation A5 à la confirmation)
    et RÉEL (`userId`) sont conservés côte à côte : l'écart n'est jamais écrasé."""

    __tablename__ = "zyloLiquidShiftPumpAssignment"
    __table_args__ = (
        # Une pompe n'a qu'UN titulaire à un instant donné ; un pompiste peut tenir PLUSIEURS pompes
        # (SOCADA : 6 pompistes pour 14 pompes) : aucune unicité (rapport, personne).
        Index("uq_zlShiftPumpAssignment_current", "reportId", "pumpLineId", unique=True, postgresql_where=text('"endsAt" IS NULL')),
        CheckConstraint(
            "kind IN ('start','break_cover','break_return','replacement','late_arrival','reassignment')",
            name="ck_zlShiftPumpAssignment_kind",
        ),
        # Seule une pompe « fermée pour ce tour » peut être sans pompiste (vérifié à la confirmation).
        CheckConstraint('"userId" IS NOT NULL OR "closedForShift"', name="ck_zlShiftPumpAssignment_user_or_closed"),
        CheckConstraint('NOT "closedForShift" OR ("userId" IS NULL AND note IS NOT NULL)', name="ck_zlShiftPumpAssignment_closed_needs_note_no_user"),
        CheckConstraint('"endsAt" IS NULL OR "endsAt" >= "startsAt"', name="ck_zlShiftPumpAssignment_period"),
        {"comment": "Segment d'affectation d'une pompe à un pompiste pendant un tour (chronologie ; prévu A5 et réel conservés)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    pumpLineId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="RESTRICT"), nullable=False, index=True,
        comment="Ligne de pompe du rapport (B3) ; la pompe est celle de la ligne.",
    )
    pumpId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidPump.id", ondelete="RESTRICT"), nullable=False, index=True,
        comment="Pompe (copie de la ligne, pour les requêtes par pompe).",
    )
    userId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Pompiste RÉEL ; nul seulement si la pompe est fermée pour ce tour.",
    )
    plannedUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True,
        comment="Pompiste PRÉVU (copie de l'affectation A5 de cette pompe), figé à la confirmation ; nul si aucun prévu. Jamais modifié.",
    )
    startsAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Début du segment ; segment de départ = ouverture du tour (la décision orale précède la saisie).")
    endsAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Fin du segment ; nulle tant qu'il est en cours (renseignée par B5).")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="start", comment="start (B4) | break_cover | break_return | replacement | late_arrival | reassignment (B5).")
    startIndex: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Index de la pompe au début du segment (index d'ouverture pour un segment de départ) ; sert à B5 pour répartir les litres.")
    closedForShift: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Pompe fermée pour ce tour : aucun pompiste, observation obligatoire.")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Observation (obligatoire si la pompe est fermée).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la saisie (≠ startsAt : la décision orale précède la saisie).")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi (RT, ou gérant à sa place).")
    # --- Colonnes ajoutées par B5 (mouvements de personnel en cours de tour) ---
    movementId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftStaffMovement.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Mouvement de personnel (B5) qui a créé ce segment ; nul pour un segment de départ (B4).",
    )
    closedByMovementId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftStaffMovement.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Mouvement (B5) qui a fermé ce segment (renseigne endsAt) ; remis à nul si ce mouvement est annulé.",
    )
    coversUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True,
        comment="Pompiste remplacé ou en pause que ce segment couvre (break_cover, replacement) ; nul sinon.",
    )
    holderIsTeamLead: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Vrai si le titulaire du segment est le chef d'équipe (remplaçant autorisé, PC-52) : marqueur figé à la création.")
    cancelledAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Renseigné quand le mouvement qui a créé ce segment est annulé : le segment est neutralisé (endsAt = startsAt), jamais supprimé, et exclu de la chronologie.",
    )


class ShiftStaffMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mouvement de personnel en cours de tour (scénario B5) : une ACTION de l'utilisateur
    (pause, retour de pause, remplacement, réaffectation) pouvant toucher plusieurs pompes.
    Il ne modifie jamais l'affectation de départ (B4) ni le planning (A5) : il ferme les
    segments en cours (`ShiftPumpAssignment.endsAt`) et en ouvre d'autres, de sorte que la
    chronologie de chaque pompe reste continue et que prévu et réel restent côte à côte.
    Un mouvement n'est jamais supprimé : il est seulement annulé (`cancelledAt`)."""

    __tablename__ = "zyloLiquidShiftStaffMovement"
    __table_args__ = (
        CheckConstraint("kind IN ('break_start','break_end','replacement','reassignment')", name="ck_zlShiftStaffMovement_kind"),
        CheckConstraint(
            "reason IS NULL OR reason IN ('absence_unforeseen','left_during_shift','rebalancing','late_arrival','pump_breakdown','other')",
            name="ck_zlShiftStaffMovement_reason",
        ),
        CheckConstraint(
            "(\"cancelledAt\" IS NULL) = (\"cancelledByUserId\" IS NULL) AND (\"cancelledAt\" IS NULL) = (\"cancelReason\" IS NULL)",
            name="ck_zlShiftStaffMovement_cancel_complete",
        ),
        Index("ix_zlShiftStaffMovement_report_occurred", "reportId", "occurredAt"),
        {"comment": "Mouvement de personnel en cours de tour (pause, retour, remplacement, réaffectation) ; jamais supprimé, seulement annulé."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, comment="break_start | break_end | replacement | reassignment.")
    occurredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Heure RÉELLE du mouvement (≤ maintenant, ≥ ouverture du tour) ; ≠ recordedAt car la décision orale précède la saisie.")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la saisie.")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi (RT ou gérant) ; le chef d'équipe décide oralement, il n'écrit pas.")
    subjectUserId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True,
        comment="Pompiste concerné : celui qui part en pause, revient ou est remplacé ; pour une réaffectation, le NOUVEAU titulaire.",
    )
    reason: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="Motif (remplacement et réaffectation) ; nul pour une pause (imposé par la nature).")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Observation ; obligatoire si motif « other » ou pompe fermée pendant la pause.")
    breakStartMovementId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidShiftStaffMovement.id", ondelete="RESTRICT"), nullable=True, index=True,
        comment="Pour un break_end : la pause terminée.",
    )
    cancelledAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Annulation du mouvement (jamais de suppression).")
    cancelledByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True)
    cancelReason: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Motif obligatoire de l'annulation.")


class ShiftReportCashLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Caisse d'UN pompiste pour UN rapport de tour (scénario D3) : ventes attribuées (calculées par le serveur à partir
    de D1 et de l'affectation B4/B5), déductions saisies (bons de crédit, paiements mobiles, autres : `manual` tant que
    C2/C3/C5/C9 n'existent pas), comptage pompiste et recomptage RT, montant théorique, remis et écart signé
    (remis - théorique). `remittedAmount` = `managerRecountedAmount`. Théorique et écart sont NULS (« non calculé »)
    quand la part du pompiste dépend d'une pompe partagée non répartie ou d'un prix absent : jamais une valeur estimée.
    Aucun lien avec `ShiftCashDeclaration` (par cuve) ni avec `Sale` (PC-15)."""

    __tablename__ = "zyloLiquidShiftReportCashLine"
    __table_args__ = (
        UniqueConstraint("reportId", "userId", name="uq_zlShiftReportCashLine_report_user"),
        CheckConstraint("\"roleMarker\" IN ('attendant','team_lead')", name="ck_zlShiftReportCashLine_roleMarker"),
        CheckConstraint("\"deductionsSource\" IN ('manual','computed')", name="ck_zlShiftReportCashLine_deductionsSource"),
        CheckConstraint("\"varianceNature\" IS NULL OR \"varianceNature\" IN ('surplus','shortage','balanced')", name="ck_zlShiftReportCashLine_varianceNature"),
        CheckConstraint(
            "\"creditVouchersAmount\" >= 0 AND \"mobilePaymentsAmount\" >= 0 AND \"otherDeductionsAmount\" >= 0 AND \"attendantCountedAmount\" >= 0 AND \"managerRecountedAmount\" >= 0",
            name="ck_zlShiftReportCashLine_amounts_nonneg",
        ),
        {"comment": "Caisse d'un pompiste pour un rapport de tour (D3) : ventes attribuées, déductions, comptage pompiste et RT, théorique, remis, écart signé."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Personne ayant tenu au moins une pompe pendant le tour (chronologie B4/B5).")
    userNameSnapshot: Mapped[str] = mapped_column(String(200), nullable=False, comment="Nom copié à l'enregistrement : le rapport reste lisible si le personnel change.")
    roleMarker: Mapped[str] = mapped_column(String(15), nullable=False, server_default="attendant", comment="attendant | team_lead (chef d'équipe remplaçant, PC-46/PC-52 : ligne marquée « CE »).")
    attributedLiters: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Litres vendus attribués au pompiste (règle PC-05) ; nul si une de ses pompes est partagée non répartie.")
    salesValue: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Valeur des ventes attribuées (somme des montants D1 attribués, prix copié) ; nul si non calculable (pompe partagée non répartie, prix absent).")
    creditVouchersAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", comment="Total des bons de crédit signés remis par le pompiste (saisi à la main tant que C2 n'existe pas).")
    mobilePaymentsAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", comment="Total des paiements mobiles encaissés par le pompiste (saisi à la main tant que C3 n'existe pas).")
    otherDeductionsAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", comment="Autres déductions (bons valeur, dépenses autorisées) ; note obligatoire si > 0.")
    otherDeductionsNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Explication des autres déductions.")
    deductionsSource: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual", comment="manual (saisie du RT) tant que C2/C3/C5/C9 n'existent pas ; computed ensuite (cellule verrouillée).")
    theoreticalAmount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Montant théorique dû = valeur des ventes - déductions ; nul (« non calculé ») si la valeur des ventes est inconnue.")
    attendantCountedAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Espèces comptées par le pompiste.")
    managerRecountedAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Espèces recomptées par le RT devant le pompiste.")
    remittedAmount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Remis = montant recompté par le RT (ce qu'il a réellement reçu).")
    countsMatch: Mapped[bool] = mapped_column(nullable=False, comment="Vrai si comptage pompiste = recomptage RT.")
    varianceAmount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Écart signé = remis - théorique (positif = excédent, négatif = manquant) ; nul si le théorique n'est pas calculé.")
    varianceNature: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="surplus (> 0) | shortage (< 0) | balanced (= 0) ; nul si non calculé.")
    documentsHandedOver: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="Bons de crédit et notes de paiement mobile physiquement remis (contrôlé en D6).")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Observation ; obligatoire si les deux comptages diffèrent.")
    basedOnClosingVersion: Mapped[int] = mapped_column(nullable=False, comment="Version de la fermeture des pompes (D1) sur laquelle repose le calcul ; différente de l'actuelle = à recalculer.")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi (RT, ou gérant à sa place).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement de la ligne.")


class ShiftReportPumpShare(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Répartition MANUELLE d'une pompe partagée sans index intermédiaire (scénario D3, PC-05) : une ligne par (ligne de
    pompe, pompiste). C'est une déclaration humaine TRACÉE (motif obligatoire, auteur, date) : le système n'estime jamais
    une part. La répartition automatique par index de changement (B5) est calculée à la lecture, jamais stockée ici."""

    __tablename__ = "zyloLiquidShiftReportPumpShare"
    __table_args__ = (
        UniqueConstraint("pumpLineId", "userId", name="uq_zlShiftReportPumpShare_line_user"),
        CheckConstraint("\"source\" IN ('manual','segment_index')", name="ck_zlShiftReportPumpShare_source"),
        CheckConstraint("\"litersShare\" >= 0", name="ck_zlShiftReportPumpShare_liters_nonneg"),
        {"comment": "Répartition manuelle (déclarée et tracée) des litres d'une pompe partagée entre ses pompistes (D3)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    pumpLineId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Ligne de pompe du rapport.")
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Pompiste ayant tenu cette pompe (chronologie B4/B5).")
    litersShare: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Litres attribués ; la somme des parts de la pompe égale ses litres vendus (D1).")
    source: Mapped[str] = mapped_column(String(15), nullable=False, server_default="manual", comment="manual (déclaration du RT) | segment_index (réservé : calculé à la lecture, non stocké).")
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Comment la répartition a été décidée (10 caractères minimum) ; obligatoire si manual.")
    declaredByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la répartition.")
    declaredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la déclaration.")


class ShiftReportCashLineCorrection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rature d'une valeur déjà enregistrée d'une ligne de caisse (scénario D3) : UNE ligne par champ modifié. L'ancienne
    valeur est CONSERVÉE (jamais d'écrasement silencieux), motif et « paraphé par » obligatoires ; aucune suppression."""

    __tablename__ = "zyloLiquidShiftReportCashLineCorrection"
    __table_args__ = (
        CheckConstraint(
            "\"field\" IN ('creditVouchersAmount','mobilePaymentsAmount','otherDeductionsAmount','attendantCountedAmount','managerRecountedAmount')",
            name="ck_zlShiftReportCashLineCorrection_field",
        ),
        CheckConstraint("\"reasonCode\" IN ('count_error','entry_error','voucher_found','index_corrected','other')", name="ck_zlShiftReportCashLineCorrection_reason"),
        {"comment": "Historique des ratures d'une ligne de caisse (comptage, déductions) : ancienne valeur conservée, motif, paraphé par."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    cashLineId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportCashLine.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Ligne de caisse corrigée.")
    field: Mapped[str] = mapped_column(String(25), nullable=False, comment="Champ modifié : creditVouchersAmount | mobilePaymentsAmount | otherDeductionsAmount | attendantCountedAmount | managerRecountedAmount.")
    oldValue: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Valeur avant la correction (conservée, jamais écrasée).")
    newValue: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Valeur après la correction.")
    reasonCode: Mapped[str] = mapped_column(String(20), nullable=False, comment="Motif : count_error | entry_error | voucher_found | index_corrected | other.")
    reasonNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »).")
    initialedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif).")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la correction (RT ou gérant).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction.")
    cashVersion: Mapped[int] = mapped_column(nullable=False, comment="Version du bloc caisse produite par cette correction.")


class ShiftReportCashAdjustment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Réglages de caisse d'un rapport de tour (scénario D5) : UNE ligne par rapport, créée au premier enregistrement. Porte la
    règle PC-03 (« ventes lubrifiants et boutique déduites » : par défaut OUI, désactivable avec motif) et la version du bloc
    de saisie D5 (verrou optimiste : dépenses, règlements, règle). Aucune valeur calculée (A à H) n'est stockée ici."""

    __tablename__ = "zyloLiquidShiftReportCashAdjustment"
    __table_args__ = (
        UniqueConstraint("reportId", name="uq_zlShiftReportCashAdjustment_report"),
        CheckConstraint("\"deductRetainedSales\" OR \"deductRetainedSalesNote\" IS NOT NULL", name="ck_zlShiftReportCashAdjustment_note_if_off"),
        {"comment": "Réglages de la caisse d'un rapport de tour (D5) : règle de déduction lubrifiants/boutique (PC-03) avec motif, version du bloc de saisie."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False)
    deductRetainedSales: Mapped[bool] = mapped_column(nullable=False, server_default="true", comment="Vrai (défaut) : les ventes de lubrifiants (rubrique 2) et de boutique (rubrique 4) sont comptées comme dépenses diverses (PC-03) ; faux : elles ne le sont plus (motif obligatoire).")
    deductRetainedSalesNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Motif de la désactivation de la déduction (10 caractères minimum) ; nul tant que la règle est active.")
    inputsVersion: Mapped[int] = mapped_column(nullable=False, server_default="0", comment="Version du bloc de saisie D5 : +1 à chaque enregistrement ; verrou optimiste (409 cash_inputs_version_changed).")
    lastRecordedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D5.")
    lastRecordedByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, comment="Auteur du dernier enregistrement D5 (RT ou gérant à sa place) ; sert au message de conflit.")


class ShiftReportExpenseLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Dépense diverse SAISIE d'un rapport de tour (scénario D5, partagée plus tard avec C9). Les lignes « Lubrifiants » et
    « Boutique » ne sont PAS stockées : elles sont calculées depuis les cumuls D4 quand la règle PC-03 est active."""

    __tablename__ = "zyloLiquidShiftReportExpenseLine"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_zlShiftReportExpenseLine_amount_positive"),
        CheckConstraint("\"receiptReference\" IS NOT NULL OR note IS NOT NULL", name="ck_zlShiftReportExpenseLine_receipt_or_note"),
        {"comment": "Dépense diverse saisie d'un rapport de tour (D5) : libellé, montant > 0, justificatif ou note."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Ordre d'affichage (1, 2, 3…).")
    label: Mapped[str] = mapped_column(String(150), nullable=False, comment="Libellé de la dépense (carburant du groupe, réparation…).")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Montant de la dépense, strictement positif, 2 décimales.")
    receiptReference: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="N° du reçu / justificatif ; nul seulement si une note explique pourquoi il n'y en a pas.")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Précision ; obligatoire sans justificatif.")
    origin: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual", comment="manual (saisie du RT) ; réservé C9 (dépense de caisse en cours de tour).")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la ligne (RT ou gérant à sa place).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'enregistrement.")


class ShiftReportSettlementLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Règlement VAL/CCT reçu pendant le tour (scénario D5) : la grandeur D de la caisse. Saisi (aucune autre source), avec
    PROPOSITIONS lues dans `Payment` ; `paymentId` rattache la ligne à un `Payment` existant (jamais créé ni modifié ici) et
    un `Payment` ne peut être compté qu'une seule fois (index unique)."""

    __tablename__ = "zyloLiquidShiftReportSettlementLine"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_zlShiftReportSettlementLine_amount_positive"),
        CheckConstraint("mode IN ('cash','cheque','loading_card')", name="ck_zlShiftReportSettlementLine_mode"),
        CheckConstraint("\"commercialAccountId\" IS NOT NULL OR \"payerLabel\" IS NOT NULL", name="ck_zlShiftReportSettlementLine_payer"),
        Index("uq_zlShiftReportSettlementLine_payment", "paymentId", unique=True, postgresql_where=text("\"paymentId\" IS NOT NULL")),
        {"comment": "Règlement VAL/CCT reçu pendant un tour (D5) : client ou payeur libre, montant, mode, référence, paiement existant éventuel."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Ordre d'affichage (1, 2, 3…).")
    commercialAccountId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=True, comment="Compte client qui règle ; nul si le payeur est saisi en texte libre.")
    payerLabel: Mapped[str | None] = mapped_column(String(150), nullable=True, comment="Payeur en texte libre (quand il n'y a pas de compte client).")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Montant du règlement, strictement positif, 2 décimales.")
    mode: Mapped[str] = mapped_column(String(15), nullable=False, comment="cash (espèces) | cheque | loading_card (carte de chargement).")
    reference: Mapped[str] = mapped_column(String(100), nullable=False, comment="Référence : n° de chèque, « PM SCT »…")
    paymentId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidPayment.id", ondelete="RESTRICT"), nullable=True, comment="Paiement existant dont la ligne provient (proposition acceptée) ; lu, jamais modifié ; unique : un paiement ne compte qu'une fois.")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la ligne (RT ou gérant à sa place).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'enregistrement.")


class ShiftReportSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """État d'UNE rubrique 2 à 7 d'un rapport de tour (D4) : une ligne par (rapport, rubrique), créée au premier enregistrement.
    L'enregistrement EST le brouillon (modifiable tant que le tour est ouvert) ; `version` = verrou optimiste (409). Le total est
    CALCULÉ par le serveur à chaque enregistrement (jamais saisi) et recopié ici pour D5/D6. Une rubrique sans ligne ici est
    « non commencée » : jamais une valeur par défaut."""

    __tablename__ = "zyloLiquidShiftReportSection"
    __table_args__ = (
        UniqueConstraint("reportId", "sectionNumber", name="uq_zlShiftReportSection_report_number"),
        CheckConstraint("\"sectionNumber\" BETWEEN 2 AND 7", name="ck_zlShiftReportSection_number"),
        CheckConstraint("status IN ('not_started','saved','ras')", name="ck_zlShiftReportSection_status"),
        CheckConstraint("\"detailMode\" IS NULL OR \"detailMode\" IN ('detailed','summary')", name="ck_zlShiftReportSection_detailMode"),
        {"comment": "État d'une rubrique 2 à 7 d'un rapport de tour (D4) : statut, mode de détail, total calculé, version (verrou optimiste)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    sectionNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Numéro de rubrique du rapport : 2 lubrifiants, 3 gaz, 4 boutique, 5 crédits clients, 6 bons valeur, 7 paiements électroniques.")
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="not_started", comment="not_started | saved (enregistrée, modifiable jusqu'à D7) | ras (barrée « rien à signaler », aucune ligne).")
    rasNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Remarque facultative saisie en barrant la rubrique RAS.")
    detailMode: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="Rubriques 4 et 7 : detailed (par catégorie / un paiement par ligne) | summary (« sans détail » / cumul par opérateur) ; nul ailleurs.")
    totalAmount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, server_default="0", comment="Total de la rubrique CALCULÉ par le serveur (somme des montants de lignes), recopié pour D5 ; jamais saisi.")
    orangeBalance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Rubrique 7 : solde du compte Orange Money noté en en-tête du papier ; informatif, jamais utilisé dans un calcul.")
    mtnBalance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Rubrique 7 : solde du compte MTN Mobile Money noté en en-tête du papier ; informatif, jamais utilisé dans un calcul.")
    version: Mapped[int] = mapped_column(nullable=False, server_default="1", comment="Version de la rubrique : 1 au premier enregistrement, +1 ensuite ; verrou optimiste (409 shift_report_sections_version_changed).")
    savedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement.")
    savedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Auteur du dernier enregistrement (RT ou gérant à sa place).")


class ShiftReportLubricantLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 2 — une ligne par référence de lubrifiant : stock d'ouverture (reporté de la fermeture du rapport précédent, ou
    saisi la première fois), entrées, ventes, fermeture CALCULÉE, prix et montant. Désignation et prix sont un INSTANTANÉ."""

    __tablename__ = "zyloLiquidShiftReportLubricantLine"
    __table_args__ = (
        UniqueConstraint("reportId", "lineKey", name="uq_zlShiftReportLubricantLine_report_key"),
        CheckConstraint("\"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportLubricantLine_openingSource"),
        CheckConstraint("\"unitPriceSource\" IS NULL OR \"unitPriceSource\" IN ('catalogue','manual')", name="ck_zlShiftReportLubricantLine_priceSource"),
        CheckConstraint("\"openingQty\" >= 0 AND \"entryQty\" >= 0 AND \"soldQty\" >= 0 AND \"closingQty\" >= 0", name="ck_zlShiftReportLubricantLine_qty_nonneg"),
        {"comment": "Rubrique 2 du rapport de tour : une ligne par référence de lubrifiant (ouverture, entrée, ventes, fermeture, prix, montant)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    lineNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Position de la ligne dans le tableau.")
    lineKey: Mapped[str] = mapped_column(String(220), nullable=False, comment="Identité de la ligne dans le rapport : p:<id produit> (catalogue) ou d:<désignation normalisée> (hors catalogue).")
    sellableProductId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSellableProduct.id", ondelete="RESTRICT"), nullable=True, comment="Produit vendable du catalogue ; nul = référence hors catalogue (avertissement D6).")
    designation: Mapped[str] = mapped_column(String(200), nullable=False, comment="Désignation COPIÉE (instantané) : le rapport reste lisible si le catalogue change.")
    openingQty: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Stock d'ouverture déclaré (jamais lu dans SellableProduct.stockQuantity, stock vif non fiable pour cette déclaration).")
    openingSource: Mapped[str] = mapped_column(String(20), nullable=False, comment="carried (fermeture du rapport précédent) | initial (première fois, saisi) | continuity_break (écart déclaré avec motif).")
    openingNote: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Motif de l'écart avec la fermeture précédente (10 caractères minimum).")
    previousLineId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportLubricantLine.id", ondelete="SET NULL"), nullable=True, comment="Ligne du rapport précédent dont la fermeture a été reportée (traçabilité).")
    entryQty: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", comment="Entrées du tour ; vide = 0.")
    soldQty: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Quantités vendues pendant le tour (≤ ouverture + entrées).")
    closingQty: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Fermeture CALCULÉE = ouverture + entrées - ventes.")
    countedQty: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="Stock physiquement compté (facultatif) ; l'écart avec la fermeture est un avertissement D6.")
    unitPriceAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True, comment="Prix unitaire figé : prix en vigueur à l'ouverture du tour (catalogue) ou saisi (hors catalogue) ; nul = prix non disponible, jamais inventé.")
    unitPriceSource: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="catalogue | manual (« prix saisi »).")
    unitPriceCurrencyId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=True, comment="Devise du prix catalogue ; nulle pour un prix saisi.")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Montant = ventes x prix arrondi à 2 décimales ; nul si le prix est indisponible.")


class ShiftReportGasLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 3 — gaz domestique : une ligne par taille de bouteille (6 ; 12,5 ; 26 ; 35 kg) et par type (bouteille, consignation,
    déconsignation). Stock (ouverture, entrées, fermeture) seulement pour les bouteilles ; consignation/déconsignation : quantité seule.
    Hypothèse à confirmer terrain (PC-D4-e) : la déconsignation est NÉGATIVE dans le montant (retour de consigne)."""

    __tablename__ = "zyloLiquidShiftReportGasLine"
    __table_args__ = (
        UniqueConstraint("reportId", "sizeKg", "lineKind", name="uq_zlShiftReportGasLine_report_size_kind"),
        CheckConstraint("\"lineKind\" IN ('bottle','deposit','deposit_refund')", name="ck_zlShiftReportGasLine_lineKind"),
        CheckConstraint("\"openingSource\" IS NULL OR \"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportGasLine_openingSource"),
        CheckConstraint("\"soldQty\" >= 0 AND (\"openingQty\" IS NULL OR \"openingQty\" >= 0) AND (\"entryQty\" IS NULL OR \"entryQty\" >= 0) AND (\"closingQty\" IS NULL OR \"closingQty\" >= 0)", name="ck_zlShiftReportGasLine_qty_nonneg"),
        {"comment": "Rubrique 3 du rapport de tour : gaz domestique par taille de bouteille (bouteille, consignation, déconsignation)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    sizeKg: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False, comment="Taille de la bouteille en kg : 6, 12.5, 26 ou 35 (tailles par défaut tant qu'aucun catalogue gaz n'existe, A3).")
    lineKind: Mapped[str] = mapped_column(String(20), nullable=False, comment="bottle (bouteille) | deposit (consignation) | deposit_refund (déconsignation, montant négatif).")
    openingQty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Bouteilles : stock d'ouverture (reporté du rapport précédent ou saisi) ; nul pour consignation/déconsignation.")
    openingSource: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="carried | initial | continuity_break (bouteilles seulement).")
    openingNote: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Motif de l'écart avec la fermeture précédente (10 caractères minimum).")
    previousLineId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportGasLine.id", ondelete="SET NULL"), nullable=True, comment="Ligne du rapport précédent dont la fermeture a été reportée.")
    entryQty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Bouteilles : entrées du tour ; nul pour consignation/déconsignation.")
    soldQty: Mapped[int] = mapped_column(Integer, nullable=False, comment="Quantité vendue (bouteilles), consignées ou déconsignées pendant le tour.")
    closingQty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Bouteilles : fermeture CALCULÉE = ouverture + entrées - ventes.")
    unitPriceAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True, comment="Prix unitaire SAISI par le RT (aucun catalogue gaz en base : jamais de prix inventé).")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="Montant CALCULÉ = quantité x prix ; négatif pour la déconsignation.")


class ShiftReportShopLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 4 — boutique (S.F.S) : une ligne par catégorie de l'imprimé (mode détaillé) ou une ligne unique « total boutique sans détail »."""

    __tablename__ = "zyloLiquidShiftReportShopLine"
    __table_args__ = (
        UniqueConstraint("reportId", "categoryCode", name="uq_zlShiftReportShopLine_report_category"),
        CheckConstraint("amount >= 0", name="ck_zlShiftReportShopLine_amount_nonneg"),
        {"comment": "Rubrique 4 du rapport de tour : ventes boutique par catégorie, ou total sans détail."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    categoryCode: Mapped[str] = mapped_column(String(30), nullable=False, comment="Code de catégorie de l'imprimé (telecards, insecticides, alcoholic_drinks…) ou `total` (mode sans détail).")
    categoryLabel: Mapped[str] = mapped_column(String(100), nullable=False, comment="Libellé français copié (instantané).")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, comment="Montant déclaré de la catégorie (≥ 0, 2 décimales).")


class ShiftReportCreditVoucher(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 5 — UNE ligne par bon de crédit client. Le bon papier est la preuve ; l'application ne voit que la déclaration du RT
    (« signé en main »). AUCUNE `Sale` ni `Receivable` n'est créée ici : `saleId`/`receivableId` sont réservés à E7 (report sur la fiche
    client via `create_sale`, idempotent) et nuls en D4. Plaque et chauffeur : lien vers la fiche (`Vehicle`/`Driver`) ou texte libre signalé."""

    __tablename__ = "zyloLiquidShiftReportCreditVoucher"
    __table_args__ = (
        UniqueConstraint("reportId", "voucherNumber", name="uq_zlShiftReportCreditVoucher_report_number"),
        Index("uq_zlShiftReportCreditVoucher_station_number", "stationId", "voucherNumber", unique=True),
        CheckConstraint("\"quantityLiters\" > 0 AND \"voucherAmount\" > 0", name="ck_zlShiftReportCreditVoucher_positive"),
        {"comment": "Rubrique 5 du rapport de tour : un bon de crédit client par ligne (client, produit, pompe, quantité, montant, plaque, chauffeur, signature déclarée)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, comment="Station du rapport (copie) : le numéro de bon est unique par station.")
    lineNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Position de la ligne dans le tableau.")
    voucherNumber: Mapped[str] = mapped_column(String(30), nullable=False, comment="Numéro imprimé sur le bon ; unique par station, tous rapports confondus.")
    commercialAccountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidCommercialAccount.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Compte client à crédit existant et actif (jamais de texte libre).")
    accountNameSnapshot: Mapped[str] = mapped_column(String(150), nullable=False, comment="Nom du compte copié : le rapport reste lisible si la fiche change.")
    vehicleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidVehicle.id", ondelete="RESTRICT"), nullable=True, comment="Véhicule de la fiche du compte ; nul si plaque en texte libre.")
    plateText: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Plaque : plaque de la fiche (copie) ou texte libre SIGNALÉ en D6 (jamais ajouté à la fiche).")
    driverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDriver.id", ondelete="RESTRICT"), nullable=True, comment="Chauffeur de la fiche (jamais un utilisateur Zylo) ; nul si texte libre.")
    driverNameText: Mapped[str | None] = mapped_column(String(150), nullable=True, comment="Nom du chauffeur : fiche (copie) ou texte libre signalé en D6.")
    fuelProductId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="RESTRICT"), nullable=False, comment="Produit carburant ; doit être celui de la cuve de la pompe indiquée.")
    fuelProductName: Mapped[str] = mapped_column(String(100), nullable=False, comment="Nom du produit copié (instantané).")
    pumpLineId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Pompe qui a servi le bon (ligne de pompe du rapport) : nécessaire à D3 (crédits servis par pompiste).")
    quantityLiters: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Litres servis (> 0, 2 décimales).")
    unitPriceAmount: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True, comment="Prix en vigueur à l'OUVERTURE du tour, figé à la première écriture ; nul = prix non disponible (jamais inventé).")
    voucherAmount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, comment="Montant INSCRIT sur le bon (> 0) : c'est lui qui est cumulé ; un écart avec quantité x prix est un avertissement, jamais un blocage.")
    servedAt: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, comment="Date et heure du bon, heure locale de la station.")
    signedConfirmed: Mapped[bool] = mapped_column(nullable=False, server_default="false", comment="« Bon signé en main » : le RT atteste détenir le bon papier signé (déclaratif, audité) ; faux bloque D6 et D7.")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Observation (exigée en D6 si écart de montant ou plaque/chauffeur hors fiche).")
    saleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidSale.id", ondelete="RESTRICT"), nullable=True, comment="RÉSERVÉ à E7 : vente à crédit créée au report sur la fiche client ; nul en D4.")
    receivableId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidReceivable.id", ondelete="RESTRICT"), nullable=True, comment="RÉSERVÉ à E7 : créance créée au report ; nul en D4.")


class ShiftReportValueVoucherLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 6 — bons valeur : nombre de bons par coupure (10 000, 5 000, 3 000) dans deux colonnes, « bons du jour » (a) et « bons en
    valeur » (c). La colonne (b) n'existe pas sur l'imprimé (PC-D4-g). Seules les lignes non nulles sont stockées."""

    __tablename__ = "zyloLiquidShiftReportValueVoucherLine"
    __table_args__ = (
        UniqueConstraint("reportId", "denomination", "voucherColumn", name="uq_zlShiftReportValueVoucherLine_report_denom_col"),
        CheckConstraint("\"voucherColumn\" IN ('daily','value')", name="ck_zlShiftReportValueVoucherLine_column"),
        CheckConstraint("\"voucherCount\" > 0", name="ck_zlShiftReportValueVoucherLine_count_positive"),
        {"comment": "Rubrique 6 du rapport de tour : nombre de bons valeur par coupure et par colonne (du jour / en valeur)."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    denomination: Mapped[int] = mapped_column(Integer, nullable=False, comment="Valeur d'un bon (10000, 5000 ou 3000).")
    voucherColumn: Mapped[str] = mapped_column(String(10), nullable=False, comment="daily (a : bons du jour) | value (c : bons en valeur).")
    voucherCount: Mapped[int] = mapped_column(Integer, nullable=False, comment="Nombre de bons (entier > 0).")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, comment="Montant CALCULÉ = nombre x coupure.")


class ShiftReportElectronicPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rubrique 7 — paiements électroniques : Tomcard / E-Pay Box (cartes, tickets, montant ; une ligne) et paiements mobile money
    (Orange Money, MTN) : une ligne par paiement (code, montant, pompe, heure) ou, en mode « cumul par opérateur », une ligne par
    opérateur sans code ni pompe (SOCADA : avertissement D6, D3 ne peut rien déduire par pompiste)."""

    __tablename__ = "zyloLiquidShiftReportElectronicPayment"
    __table_args__ = (
        UniqueConstraint("reportId", "lineKey", name="uq_zlShiftReportElectronicPayment_report_key"),
        Index(
            "uq_zlShiftReportElectronicPayment_station_operator_code", "stationId", "operator", "transactionCode",
            unique=True, postgresql_where=text('"transactionCode" IS NOT NULL'),
        ),
        CheckConstraint("kind IN ('tomcard','mobile')", name="ck_zlShiftReportElectronicPayment_kind"),
        CheckConstraint("operator IS NULL OR operator IN ('orange_money','mtn_momo')", name="ck_zlShiftReportElectronicPayment_operator"),
        CheckConstraint("(kind = 'mobile') = (operator IS NOT NULL)", name="ck_zlShiftReportElectronicPayment_operator_iff_mobile"),
        CheckConstraint("amount >= 0", name="ck_zlShiftReportElectronicPayment_amount_nonneg"),
        CheckConstraint("origin IS NULL OR origin IN ('pump','shop','other')", name="ck_zlShiftReportElectronicPayment_origin"),
        CheckConstraint("COALESCE(origin, '') = 'pump' OR \"pumpLineId\" IS NULL", name="ck_zlShiftReportElectronicPayment_pump_only_if_origin_pump"),
        {"comment": "Rubrique 7 du rapport de tour : Tomcard / E-Pay Box et paiements Orange Money / MTN Mobile Money."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="CASCADE"), nullable=False, index=True)
    stationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="RESTRICT"), nullable=False, comment="Station du rapport (copie) : un code de paiement est unique par station et par opérateur.")
    lineNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Position de la ligne dans le tableau.")
    lineKey: Mapped[str] = mapped_column(String(80), nullable=False, comment="Identité de la ligne : tomcard | <opérateur>:<code> (détail) | <opérateur>:summary (cumul).")
    kind: Mapped[str] = mapped_column(String(10), nullable=False, comment="tomcard (Tomcard / E-Pay Box) | mobile (mobile money).")
    operator: Mapped[str | None] = mapped_column(String(15), nullable=True, comment="orange_money | mtn_momo (paiements mobile money seulement).")
    cardCount: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Tomcard : nombre de cartes ; nul sinon.")
    ticketCount: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Tomcard : nombre de tickets ; nul sinon.")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, comment="Montant de la ligne (≥ 0, 2 décimales).")
    transactionCode: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="Code du paiement mobile (majuscules) : obligatoire en mode détail, unique par station et opérateur ; nul en mode cumul.")
    origin: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="Origine d'un paiement mobile en mode détail : pump (reçu à une pompe) | shop (boutique) | other ; nulle en mode cumul et pour Tomcard. La pompe n'est obligatoire que si origin = pump.")
    pumpLineId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReportPumpLine.id", ondelete="RESTRICT"), nullable=True, index=True, comment="Pompe qui a reçu le paiement (obligatoire si origin = pump, nulle sinon) : sert à D3 (paiements mobiles par pompiste).")
    receivedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, comment="Heure du paiement, heure locale de la station (facultative).")


class ShiftReportSectionCorrection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rature d'une valeur déjà enregistrée d'une rubrique 2 à 7 (D4) : UNE ligne par champ modifié ou ligne retirée. L'ancienne valeur est
    CONSERVÉE (jamais d'écrasement silencieux), motif et « paraphé par » obligatoires (cahier : une rature est paraphée). Historique
    conservé tant que le rapport n'est pas signé ; visible du gérant."""

    __tablename__ = "zyloLiquidShiftReportSectionCorrection"
    __table_args__ = (
        CheckConstraint("\"sectionNumber\" BETWEEN 2 AND 7", name="ck_zlShiftReportSectionCorrection_number"),
        CheckConstraint("\"reasonCode\" IN ('entry_error','count_error','voucher_found','price_corrected','other')", name="ck_zlShiftReportSectionCorrection_reason"),
        {"comment": "Historique des ratures des rubriques 2 à 7 du rapport de tour : ancienne valeur conservée, motif, paraphé par."},
    )

    reportId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidShiftReport.id", ondelete="RESTRICT"), nullable=False, index=True)
    sectionNumber: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Rubrique corrigée (2 à 7).")
    lineKey: Mapped[str] = mapped_column(String(220), nullable=False, comment="Identité de la ligne corrigée (voir la table de la rubrique).")
    field: Mapped[str] = mapped_column(String(40), nullable=False, comment="Champ modifié, ou `line` pour une ligne retirée.")
    oldValue: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Valeur avant la correction (texte, conservée) ; nulle si le champ était vide.")
    newValue: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="Valeur après la correction ; nulle si le champ est vidé ou la ligne retirée.")
    reasonCode: Mapped[str] = mapped_column(String(20), nullable=False, comment="Motif : entry_error | count_error | voucher_found | price_corrected | other.")
    reasonNote: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »).")
    initialedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif).")
    recordedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, comment="Qui a saisi la correction (RT ou gérant).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction.")
    sectionVersion: Mapped[int] = mapped_column(nullable=False, comment="Version de la rubrique produite par cette correction.")
