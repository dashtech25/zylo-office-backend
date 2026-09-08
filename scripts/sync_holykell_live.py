"""Pont temps réel : Station Simulator -> Holykell Simulator -> Zylo Liquid.

Démonstration end-to-end (délai de présentation) :
1) Provisionne les entités Zylo Liquid (stations/cuves/calibration/comptes
   Holykell/associations capteur) à partir des données réelles de
   station_sim (capacité/géométrie/calibration) et holykell_sim (mapping
   flag<->sensorId<->cuve, seule source qui connaît ce mapping — Holykell ne
   connaît ni produit ni cuve, cf. audit "appel-vers-holykell-h-smarlink.md").
2) Boucle de synchronisation : interroge l'API PUBLIQUE de holykell-simulator
   (le même contrat que h-smartlink.com) pour lire sensorWayList, écrit dans
   TankMeasurement + met à jour HolykellDeviceRegistry, puis exécute les
   algorithmes déjà validés (run_alert_evaluation_for_tank).

Usage : .venv/bin/python scripts/sync_holykell_live.py

Configuration (variables d'environnement, voir .env.example) — toutes ont un
défaut de dev local identique au comportement précédent (URLs en dur), donc
rien ne casse si elles ne sont pas définies ; en production/VPS, définir ces
variables pour pointer vers les simulateurs réellement déployés au lieu de
localhost :
  HOLYKELL_SYNC_BASE_URL   URL de l'API holykell-simulator (ex. https://holykell-sim.<domaine>)
  HOLYKELL_SYNC_USERNAME   identifiant du compte Holykell utilisé pour la sync
  HOLYKELL_SYNC_PASSWORD   mot de passe du compte Holykell utilisé pour la sync
  HOLYKELL_SYNC_ORG_ID     organisation Zylo Liquid provisionnée par ce script
  STATION_SIM_DSN          DSN PostgreSQL direct vers la base station_sim (lecture
                            de la géométrie/calibration réelle des cuves simulées)
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.auth import models as _auth_models  # noqa: F401,E402
from app.billing import models as _billing_models  # noqa: F401,E402
from app.identity import models as _identity_models  # noqa: F401,E402
from app.modules_registry import models as _modules_registry_models  # noqa: F401,E402
from app.rbac import models as _rbac_models  # noqa: F401,E402
from app.shared import geo as _shared_geo_models  # noqa: F401,E402
from app.shared import currency as _shared_currency_models  # noqa: F401,E402
from app.modules.zylo_liquid.models import (  # noqa: E402
    FuelProduct,
    HolykellAccount,
    HolykellDeviceRegistry,
    Station,
    Tank,
    TankCalibrationPoint,
    TankSensorMapping,
    TankMeasurement,
)
from app.modules.zylo_liquid.service import run_alert_evaluation_for_tank, run_delivery_detection_for_tank  # noqa: E402

ORG_ID = os.environ.get("HOLYKELL_SYNC_ORG_ID", "0879158e-0e28-45d7-8688-be2c81c96b37")
HOLY_BASE = os.environ.get("HOLYKELL_SYNC_BASE_URL", "http://localhost:8500")
HOLY_USERNAME = os.environ.get("HOLYKELL_SYNC_USERNAME", "jb.essomba")
HOLY_PASSWORD = os.environ.get("HOLYKELL_SYNC_PASSWORD", "test1234")
STATION_SIM_DSN = os.environ.get("STATION_SIM_DSN", "postgresql://zylo:zylo@localhost:5432/station_sim")

KIND_TO_MEASUREMENT_TYPE = {"product": "product_level", "water": "water_level", "temp": "temperature"}
FUEL_NAMES = {"SP": "Super sans plomb", "GO": "Gasoil", "GOI": "Gasoil Industriel"}
FUEL_ALPHA = {"SP": 0.00120, "GO": 0.00085, "GOI": 0.00085}
POLL_INTERVAL_SEC = 5


def fetch_station_sim_data():
    conn = psycopg2.connect(STATION_SIM_DSN)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    cur = conn.cursor()
    cur.execute("SELECT * FROM stations ORDER BY id")
    stations = cur.fetchall()
    cur.execute("SELECT * FROM tanks ORDER BY station_id, tank_number")
    tanks = cur.fetchall()
    cur.execute("SELECT * FROM calibration_points ORDER BY tank_id, height_mm")
    points = cur.fetchall()
    conn.close()
    tanks_by_station = {}
    for t in tanks:
        tanks_by_station.setdefault(t["station_id"], []).append(t)
    points_by_tank = {}
    for p in points:
        points_by_tank.setdefault(p["tank_id"], []).append(p)
    return stations, tanks_by_station, points_by_tank


async def provision(db, holy_stations, ss_stations, ss_tanks_by_station, ss_points_by_tank):
    fuel_product_by_code: dict[str, FuelProduct] = {}
    existing_fp = (await db.execute(select(FuelProduct).where(FuelProduct.organizationId == ORG_ID))).scalars().all()
    for fp in existing_fp:
        fuel_product_by_code[fp.code] = fp

    holy_account = (await db.execute(select(HolykellAccount).where(HolykellAccount.organizationId == ORG_ID))).scalar_one_or_none()
    if holy_account is None:
        holy_account = HolykellAccount(
            organizationId=ORG_ID, holykellUsername=HOLY_USERNAME, holykellPassword=HOLY_PASSWORD,
            syncEnabled=True, lastSyncStatus="success", lastSyncAt=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(holy_account)
        await db.flush()

    ss_by_serial = {s["holykell_serial"]: s for s in ss_stations}

    tank_id_by_sensor: dict[int, tuple] = {}  # hkSensorId -> (zylo Tank, measurementType)

    for hg in holy_stations:
        for hd in hg["devices"]:
            serial = hd["serial_number"]
            ss_station = ss_by_serial.get(serial)
            if ss_station is None:
                continue

            station = (await db.execute(
                select(Station).where(Station.organizationId == ORG_ID, Station.code == serial)
            )).scalar_one_or_none()
            if station is None:
                station = Station(
                    organizationId=ORG_ID, name=ss_station["name"], code=serial,
                    holykellGroupId=hg["group_id"],
                )
                db.add(station)
                await db.flush()

            ss_tanks = ss_tanks_by_station.get(ss_station["id"], [])
            ss_tanks_by_number = {t["tank_number"]: t for t in ss_tanks}

            for hsensor in hd["sensors"]:
                fuel_code = ss_tanks_by_number.get(hsensor["tank_number"], {}).get("fuel")
                if fuel_code and fuel_code not in fuel_product_by_code:
                    fp = FuelProduct(
                        organizationId=ORG_ID, name=FUEL_NAMES.get(fuel_code, fuel_code), code=fuel_code,
                        thermalExpansionCoefficient=FUEL_ALPHA.get(fuel_code),
                    )
                    db.add(fp)
                    await db.flush()
                    fuel_product_by_code[fuel_code] = fp

            for tank_number, ss_tank in ss_tanks_by_number.items():
                tank = (await db.execute(
                    select(Tank).where(Tank.stationId == station.id, Tank.tankNumber == tank_number)
                )).scalar_one_or_none()
                fuel_product = fuel_product_by_code[ss_tank["fuel"]]
                if tank is None:
                    tank = Tank(
                        stationId=station.id, fuelProductId=fuel_product.id, tankNumber=tank_number,
                        displayName=f"Cuve {tank_number}",
                        capacityLiters=ss_tank["capacity_l"],
                        tankHeightMm=ss_tank["diameter_mm"],
                        heightAlarmMm=ss_tank["height_alarm_mm"] or (ss_tank["diameter_mm"] * 0.92),
                        heightAlertMm=ss_tank["height_alert_mm"] or (ss_tank["diameter_mm"] * 0.85),
                        lowAlarmMm=ss_tank["low_alarm_mm"] or (ss_tank["diameter_mm"] * 0.10),
                        alertWaterMaxMm=ss_tank["water_alarm_mm"] or 25.0,
                    )
                    db.add(tank)
                    await db.flush()

                    existing_points = (await db.execute(
                        select(TankCalibrationPoint).where(TankCalibrationPoint.tankId == tank.id)
                    )).scalars().first()
                    if existing_points is None:
                        for p in ss_points_by_tank.get(ss_tank["id"], []):
                            db.add(TankCalibrationPoint(tankId=tank.id, heightMm=p["height_mm"], volumeLiters=p["volume_liters"]))

                for hsensor in hd["sensors"]:
                    if hsensor["tank_number"] != tank_number:
                        continue
                    measurement_type = KIND_TO_MEASUREMENT_TYPE[hsensor["kind"]]
                    sensor_id = hsensor["sensor_id"]

                    registry = (await db.execute(
                        select(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId == sensor_id)
                    )).scalar_one_or_none()
                    if registry is None:
                        registry = HolykellDeviceRegistry(
                            holykellAccountId=holy_account.id,
                            hkGroupId=hg["group_id"], hkGroupName=hg["group_name"],
                            hkDeviceId=hd["device_id"], hkDeviceName=serial,
                            hkSerialNumber=serial, hkProtocol="MQTT_MODBUS",
                            hkSensorId=sensor_id,
                            hkSensorName=f"{measurement_type} {hsensor['name']}",
                            hkUnit=hsensor["unit"],
                            syncFrom=datetime.now(timezone.utc).replace(tzinfo=None),
                            discoveredAt=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                        db.add(registry)
                        await db.flush()

                    mapping = (await db.execute(
                        select(TankSensorMapping).where(
                            TankSensorMapping.tankId == tank.id, TankSensorMapping.measurementType == measurement_type
                        )
                    )).scalar_one_or_none()
                    if mapping is None:
                        db.add(TankSensorMapping(
                            hkSensorId=sensor_id, tankId=tank.id, measurementType=measurement_type,
                            validFrom=datetime.now(timezone.utc).replace(tzinfo=None), active=True,
                            createdAt=datetime.now(timezone.utc).replace(tzinfo=None),
                        ))
                    tank_id_by_sensor[sensor_id] = (tank.id, measurement_type)

    await db.commit()
    return tank_id_by_sensor


async def poll_once(db, client: httpx.AsyncClient, access_token: str, tenant_id: str, sensor_to_tank: dict):
    resp = await client.get(
        f"{HOLY_BASE}/admin-api/business/deviceGroup/",
        headers={"Authorization": f"Bearer {access_token}", "tenant-id": tenant_id},
    )
    resp.raise_for_status()
    groups = resp.json().get("data", [])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    touched_tank_ids = set()

    for g in groups:
        for device in g.get("deviceList", []):
            serial = device["serialNumber"]
            status = device.get("status", 1)
            sensor_way_list = device.get("sensorWayList") or {}

            # Le TSL donne flag->sensorId ; sensorWayList donne flag->value.
            tsl_raw = device.get("tsl")
            import json as _json
            flag_to_sensor_id = {}
            if tsl_raw:
                try:
                    tsl = _json.loads(tsl_raw)
                    for sd in tsl.get("sensorDatas", []):
                        flag_to_sensor_id[str(sd["flag"])] = sd["sensorId"]
                except Exception:
                    pass

            for flag, value in sensor_way_list.items():
                sensor_id = flag_to_sensor_id.get(str(flag))
                if sensor_id is None or sensor_id not in sensor_to_tank:
                    continue
                tank_id, measurement_type = sensor_to_tank[sensor_id]

                registry = (await db.execute(
                    select(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId == sensor_id)
                )).scalar_one_or_none()
                if registry is None:
                    continue
                registry.lastValue = value
                registry.lastValueAt = now
                registry.hkLastStatus = 1 if status == 1 else 0
                # Une ingestion réussie EST une visibilité du capteur : sans
                # cela, `hkLastSeenAt` (affiché « Dernière visibilité » dans
                # l'ATG) resterait NULL à jamais — aucun autre chemin d'écriture.
                registry.hkLastSeenAt = now

                db.add(TankMeasurement(
                    hkSensorId=sensor_id, hkDeviceSerial=serial, hkSensorName=registry.hkSensorName,
                    hkUnit=registry.hkUnit, measuredAt=now, receivedAt=now, rawValue=value, insertedAt=now,
                ))
                touched_tank_ids.add(tank_id)

    holy_account = (await db.execute(select(HolykellAccount).where(HolykellAccount.organizationId == ORG_ID))).scalar_one_or_none()
    if holy_account is not None:
        holy_account.lastSyncAt = now
        holy_account.lastSyncStatus = "success"
        holy_account.lastSyncError = None

    await db.commit()

    for tank_id in touched_tank_ids:
        await run_alert_evaluation_for_tank(db, tank_id)
        # Manquait jusqu'ici : seule l'évaluation des alertes tournait en
        # continu, jamais la détection de livraison — aucune livraison
        # n'était donc jamais créée automatiquement, même après des heures
        # de sync réelle. `run_delivery_detection_for_tank` est déjà
        # idempotent (contrainte tankId+startTime) et documenté comme
        # "traitement de fond" à brancher sur un scheduler réel (service.py) —
        # ce point de sync est ce scheduler.
        await run_delivery_detection_for_tank(db, tank_id)


async def get_holykell_token(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{HOLY_BASE}/admin-api/system/auth/login", json={"username": HOLY_USERNAME, "password": HOLY_PASSWORD})
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["accessToken"], data["tenantId"]


async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{HOLY_BASE}/internal/stations")
        holy_stations = resp.json()

    ss_stations, ss_tanks_by_station, ss_points_by_tank = fetch_station_sim_data()

    async with AsyncSessionLocal() as db:
        sensor_to_tank = await provision(db, holy_stations, ss_stations, ss_tanks_by_station, ss_points_by_tank)
        print(f"Provisionné : {len(sensor_to_tank)} capteurs mappés sur des cuves Zylo Liquid.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        access_token, tenant_id = await get_holykell_token(client)
        print("Connecté à Holykell Simulator, boucle de synchronisation démarrée (Ctrl+C pour arrêter)...")
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await poll_once(db, client, access_token, tenant_id, sensor_to_tank)
                print(f"[{datetime.now().isoformat(timespec='seconds')}] cycle de synchronisation OK")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    access_token, tenant_id = await get_holykell_token(client)
                else:
                    print("Erreur HTTP:", e)
                    await _mark_sync_failed(str(e))
            except Exception as e:
                print("Erreur cycle de sync:", repr(e))
                await _mark_sync_failed(repr(e))
            await asyncio.sleep(POLL_INTERVAL_SEC)


async def _mark_sync_failed(error: str):
    async with AsyncSessionLocal() as db:
        holy_account = (await db.execute(select(HolykellAccount).where(HolykellAccount.organizationId == ORG_ID))).scalar_one_or_none()
        if holy_account is not None:
            holy_account.lastSyncStatus = "failed"
            holy_account.lastSyncError = error[:500]
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
