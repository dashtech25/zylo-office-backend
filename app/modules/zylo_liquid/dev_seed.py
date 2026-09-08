"""Jeu de données de démonstration Zylo Liquid — développement uniquement.

Aucun endpoint HTTP n'expose ce module. Il alimente une organisation vide
avec un réseau complet (produits, stations, cuves, capteurs, historique de
mesures, prix) pour que le tableau de bord réseau (frontend) ait des
données réelles à afficher sans dépendre d'une synchronisation Holykell
réelle. Toutes les entités créées passent par les mêmes fonctions de
service que l'API HTTP (`create_fuel_product`, `create_station`,
`create_tank`, `create_price_history`) et par les mêmes algorithmes
métier déjà validés (`run_delivery_detection_for_tank`,
`run_leak_test_for_tank`, `run_alert_evaluation_for_tank`) — aucun résultat
n'est inséré à la main, il est produit par le même code que la production.

Identifiable comme donnée de développement : codes de station préfixés
`DEMO-`, comptes/capteurs Holykell préfixés `DEMO-`. Idempotent : ne fait
rien si l'organisation a déjà au moins une station.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zylo_liquid import service
from app.modules.zylo_liquid.models import (
    HolykellAccount,
    HolykellDeviceRegistry,
    Station,
    TankCalibrationPoint,
    TankMeasurement,
    TankSensorMapping,
)
from app.modules.zylo_liquid.schemas import (
    CreateFuelProductRequest,
    CreatePriceHistoryRequest,
    CreateStationRequest,
    CreateTankRequest,
)
from app.shared.currency import Currency
from app.shared.geo import City

TANK_HEIGHT_MM = 3000.0

# (station_code, station_name, tank_number, product_key, capacity_liters, current_height_mm, offline)
TANK_SPECS = [
    ("DEMO-CTR", "Station Centrale", 1, "SP", 20000, 1800, False),
    ("DEMO-CTR", "Station Centrale", 2, "GO", 15000, 1650, False),
    ("DEMO-NRD", "Station Nord", 1, "GO", 18000, 300, False),
    ("DEMO-SUD", "Station Sud", 1, "SP", 12000, 1900, False),
    ("DEMO-SUD", "Station Sud", 2, "PET", 10000, 2950, False),
    ("DEMO-EST", "Station Est", 1, "PET", 8000, 1500, True),
    ("DEMO-OUE", "Station Ouest", 1, "GO", 10000, 1500, False),
]

PRICE_BY_PRODUCT = {"SP": 730, "GO": 685, "PET": 610}

DELIVERY_TANK_KEY = ("DEMO-CTR", 1)
LEAK_TANK_KEY = ("DEMO-OUE", 1)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_or_create_currency(db: AsyncSession, code: str, name: str, symbol: str) -> Currency:
    existing = (await db.execute(select(Currency).where(Currency.code == code))).scalar_one_or_none()
    if existing is not None:
        return existing
    currency = Currency(code=code, name=name, symbol=symbol, decimalPlaces=0)
    db.add(currency)
    await db.flush()
    return currency


async def seed_demo_network(
    db: AsyncSession, organization_id: uuid.UUID, owner_user_id: uuid.UUID, city_id: uuid.UUID | None = None
) -> dict:
    """`city_id` : ville Core à utiliser pour les stations. Si omis, retombe
    sur "Douala" (référentiel réel déjà présent en base de développement) —
    les tests fournissent explicitement une ville dédiée plutôt que de
    dépendre de données de développement absentes de la base de test."""
    already = (
        await db.execute(select(Station.id).where(Station.organizationId == organization_id).limit(1))
    ).scalar_one_or_none()
    if already is not None:
        return {"skipped": True, "reason": "organization_already_has_stations"}

    if city_id is not None:
        city = await db.get(City, city_id)
    else:
        city = (await db.execute(select(City).where(City.name == "Douala"))).scalar_one_or_none()
    if city is None:
        raise RuntimeError(
            "Ville introuvable dans le référentiel géographique Core — "
            "seed impossible sans une ville existante (fournir city_id explicitement)."
        )

    await _get_or_create_currency(db, "XAF", "Franc CFA (BEAC)", "FCFA")
    await db.commit()

    fuel_products = {
        "SP": await service.create_fuel_product(
            db, organization_id,
            CreateFuelProductRequest(name="Super", code="SP", densityGPerCm3=0.745, thermalExpansionCoefficient=0.00120, displayColor="#3498DB"),
        ),
        "GO": await service.create_fuel_product(
            db, organization_id,
            CreateFuelProductRequest(name="Gasoil", code="GO", densityGPerCm3=0.832, thermalExpansionCoefficient=0.00085, displayColor="#27AE60"),
        ),
        "PET": await service.create_fuel_product(
            db, organization_id,
            CreateFuelProductRequest(name="Pétrole", code="PET", densityGPerCm3=0.810, displayColor="#8E44AD"),
        ),
    }

    stations: dict[str, Station] = {}
    for station_code, station_name, *_ in TANK_SPECS:
        if station_code in stations:
            continue
        stations[station_code] = await service.create_station(
            db, organization_id, owner_user_id,
            CreateStationRequest(name=station_name, code=station_code, cityId=city.id, address=f"{station_name}, Douala", phone="+237600000000"),
        )

    holykell_account = HolykellAccount(
        organizationId=organization_id,
        holykellUsername="demo-account",
        holykellPassword="demo-password-not-real",
        syncEnabled=True,
        lastSyncAt=_now(),
        lastSyncStatus="success",
    )
    db.add(holykell_account)
    await db.flush()

    now = _now()
    tanks: dict[tuple[str, int], dict] = {}
    # hkSensorId est unique GLOBALEMENT (registre Holykell partagé entre
    # organisations dans la réalité, uq_zlHolykellDevice_hkSensorId_global)
    # — jamais une plage fixe, qui entrerait en conflit dès la deuxième
    # organisation de démonstration seedée.
    current_max_sensor_id = await db.scalar(select(func.max(HolykellDeviceRegistry.hkSensorId)))
    next_sensor_id = max(900001, (current_max_sensor_id or 0) + 1)
    for station_code, _station_name, tank_number, product_key, capacity, current_height_mm, offline in TANK_SPECS:
        station = stations[station_code]
        product = fuel_products[product_key]
        tank = await service.create_tank(
            db, organization_id, owner_user_id,
            CreateTankRequest(
                stationId=station.id, tankNumber=tank_number, displayName=f"Cuve {tank_number}",
                capacityLiters=capacity, tankHeightMm=TANK_HEIGHT_MM, fuelProductId=product.id,
                heightAlarmMm=TANK_HEIGHT_MM - 100, heightAlertMm=TANK_HEIGHT_MM - 300, lowAlarmMm=400,
            ),
        )
        db.add(TankCalibrationPoint(tankId=tank.id, heightMm=0, volumeLiters=0))
        db.add(TankCalibrationPoint(tankId=tank.id, heightMm=TANK_HEIGHT_MM, volumeLiters=capacity))

        sensor_id = next_sensor_id
        next_sensor_id += 1
        registry = HolykellDeviceRegistry(
            holykellAccountId=holykell_account.id, hkGroupId=1, hkGroupName="Réseau démo",
            hkDeviceId=sensor_id, hkSerialNumber=f"DEMO-{sensor_id}", hkSensorId=sensor_id,
            hkSensorName=f"product_level {tank.displayName}", hkUnit="mm", sensorCategory="physical",
            isMapped=True, mappedAt=now,
            # Une sonde hors ligne conserve sa dernière valeur connue (avant
            # la coupure) — lastValue=None correspondrait à "jamais configurée"
            # (sensorStatus="not_configured"), un cas différent de "hors ligne"
            # (hkLastStatus=0, get_tank_current_state / run_alert_evaluation_for_tank).
            lastValue=current_height_mm,
            lastValueAt=(now - timedelta(days=2)) if offline else now,
            hkLastStatus=0 if offline else 1,
            syncFrom=now - timedelta(days=14), discoveredAt=now - timedelta(days=14),
        )
        db.add(registry)
        await db.flush()

        db.add(TankSensorMapping(
            hkSensorId=sensor_id, tankId=tank.id, measurementType="product_level",
            validFrom=now - timedelta(days=14), active=True, createdAt=now,
        ))

        await service.create_price_history(
            db, organization_id, owner_user_id,
            CreatePriceHistoryRequest(
                stationId=station.id, fuelProductId=product.id, priceAmount=PRICE_BY_PRODUCT[product_key],
                effectiveFrom=now - timedelta(days=30), changeReason="Prix initial (jeu de données de démonstration)",
            ),
        )

        tanks[(station_code, tank_number)] = {
            "tank": tank, "sensorId": sensor_id, "currentHeight": current_height_mm,
            "offline": offline, "capacity": capacity,
        }

    await db.commit()

    leak_window = _seed_measurement_history(db, tanks, now)
    await db.commit()

    for key, entry in tanks.items():
        # L'évaluation des alertes doit tourner même pour une cuve hors ligne
        # — c'est justement elle qui doit produire l'alerte "sensor_offline"
        # (run_alert_evaluation_for_tank gère ce cas via hkLastStatus == 0).
        # Seule la détection de livraison est sautée : aucune measurement
        # n'a été seedée pour une cuve dont la sonde est hors service.
        if not entry["offline"]:
            await service.run_delivery_detection_for_tank(db, entry["tank"].id)
        await service.run_alert_evaluation_for_tank(db, entry["tank"].id)

    leak_tank_id = tanks[LEAK_TANK_KEY]["tank"].id
    await service.run_leak_test_for_tank(db, leak_tank_id, leak_window[0], leak_window[1])

    return {"skipped": False, "stationCount": len(stations), "tankCount": len(tanks)}


def _seed_measurement_history(db: AsyncSession, tanks: dict[tuple[str, int], dict], now: datetime) -> tuple[datetime, datetime]:
    """Historique de mesures product_level sur 14 jours (4 relevés/jour) —
    trajectoire sinusoïdale légère autour de la hauteur actuelle pour la
    plupart des cuves (donne un vrai signal au graphique de tendance sans
    inventer des chiffres arbitraires point par point), sauf :
    - DEMO-CTR/1 : deux paliers plats séparés par un saut ≥50mm, pour que
      `detect_deliveries` (seuils réels, Point 8) détecte une vraie
      livraison au lieu d'en insérer une à la main ;
    - DEMO-OUE/1 : deux relevés à horodatage exact espacés de 6h avec une
      baisse nette, pour que `run_leak_test_for_tank` calcule un vrai taux
      de fuite au-dessus du seuil EPA (0.38 L/H) sur cette fenêtre précise.
    """
    leak_window: tuple[datetime, datetime] | None = None

    for key, entry in tanks.items():
        if entry["offline"]:
            db.add(TankMeasurement(
                hkSensorId=entry["sensorId"], hkDeviceSerial=f"DEMO-{entry['sensorId']}",
                measuredAt=now - timedelta(days=2), receivedAt=now - timedelta(days=2),
                rawValue=entry["currentHeight"], insertedAt=now - timedelta(days=2),
            ))
            continue

        current_height = entry["currentHeight"]
        is_delivery_tank = key == DELIVERY_TANK_KEY

        for day_offset in range(14, -1, -1):
            for hour in (2, 8, 14, 20):
                measured_at = (now - timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
                if measured_at > now:
                    continue

                if is_delivery_tank:
                    height = (current_height - 450.0) if day_offset >= 4 else current_height
                else:
                    # Amplitude volontairement petite (<< seuil de hausse de 50mm de
                    # detect_deliveries) pour ne jamais déclencher de fausse livraison
                    # sur une cuve qui n'en a pas réellement une dans son historique.
                    phase = (day_offset * 4 + hour / 6) / 28 * 2 * math.pi
                    amplitude = min(current_height, TANK_HEIGHT_MM - current_height, 12.0)
                    height = current_height + amplitude * math.sin(phase)

                height = max(0.0, min(TANK_HEIGHT_MM, height))
                db.add(TankMeasurement(
                    hkSensorId=entry["sensorId"], hkDeviceSerial=f"DEMO-{entry['sensorId']}",
                    measuredAt=measured_at, receivedAt=measured_at,
                    rawValue=round(height, 1), insertedAt=measured_at,
                ))

        if key == LEAK_TANK_KEY:
            leak_start = (now - timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
            leak_end = now.replace(minute=0, second=0, microsecond=0)
            db.add(TankMeasurement(
                hkSensorId=entry["sensorId"], hkDeviceSerial=f"DEMO-{entry['sensorId']}",
                measuredAt=leak_start, receivedAt=leak_start, rawValue=current_height + 15.0, insertedAt=leak_start,
            ))
            db.add(TankMeasurement(
                hkSensorId=entry["sensorId"], hkDeviceSerial=f"DEMO-{entry['sensorId']}",
                measuredAt=leak_end, receivedAt=leak_end, rawValue=current_height, insertedAt=leak_end,
            ))
            leak_window = (leak_start, leak_end)

    return leak_window
