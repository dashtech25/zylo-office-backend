"""Tests du flux de livraison station (mission « flux de livraison station »,
2026-09-10) : déclenchement automatique du rapprochement dans les deux sens
(à la déclaration, à la détection) et génération automatique des alertes
`delivery_discrepancy`/`delivery_undeclared`/`delivery_declaration_pending`
— aucune de ces alertes n'était créée avant cette mission (le rapprochement
n'était qu'un calcul à la demande, jamais alerté)."""

import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import Alert, DeliveryDetected, TankMeasurement
from app.modules.zylo_liquid.service import run_delivery_detection_for_tank
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _setup_station_product_tank(client: AsyncClient, headers: dict, suffix: str) -> tuple[str, str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {suffix}", "code": f"P{suffix[:8]}"}, headers=headers)
    fuel_product_id = fp_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "tankNumber": 1, "displayName": f"Cuve {suffix}",
            "capacityLiters": 20000, "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        },
        headers=headers,
    )
    return station_id, fuel_product_id, tank_res.json()["id"]


async def _setup_tank_with_sensor_and_calibration(client: AsyncClient, headers: dict, organization_id: str, suffix: str) -> tuple[str, str, str, int]:
    """Variante de _setup_station_product_tank câblée pour la vraie
    détection automatique (sonde + calibration), même pattern que
    test_zylo_liquid_deliveries.py."""
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id, "tankNumber": 1, "displayName": f"Cuve {suffix}", "capacityLiters": 30000, "tankHeightMm": 2000,
            "newFuelProductName": f"Produit {suffix}", "newFuelProductCode": suffix[:10],
            "heightAlarmMm": 1900, "heightAlertMm": 1800, "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]
    fuel_product_id = tank_res.json()["fuelProductId"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 445, "volumeLiters": 5200}, {"heightMm": 1293, "volumeLiters": 16075}]},
        headers=headers,
    )
    serial = f"XM_FLOW_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return station_id, fuel_product_id, tank_id, sensor_id


async def _insert_delivery_measurement_series(sensor_id: int, base: datetime) -> None:
    """Même signature de livraison que test_zylo_liquid_deliveries.py
    (hausse 445mm -> 1298mm puis stabilisation à 1293mm), avec un point de
    départ (`base`) paramétrable pour placer la livraison à une date
    choisie par le test appelant."""
    series = [
        (base, 445), (base + timedelta(minutes=5), 490), (base + timedelta(minutes=10), 601),
        (base + timedelta(minutes=15), 748), (base + timedelta(hours=1, minutes=10), 1240),
        (base + timedelta(hours=1, minutes=15), 1298), (base + timedelta(hours=1, minutes=20), 1295),
        (base + timedelta(hours=1, minutes=25), 1293), (base + timedelta(hours=1, minutes=30), 1293),
    ]
    async with AsyncSessionLocal() as db:
        for measured_at, height in series:
            db.add(TankMeasurement(
                hkSensorId=sensor_id, hkDeviceSerial="XM_FLOW", hkUnit="mm", measuredAt=measured_at,
                rawValue=height, insertedAt=datetime.utcnow(), isCorrection=False,
            ))
        await db.commit()


async def _active_alerts(tank_id: str) -> list[Alert]:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(Alert).where(Alert.tankId == uuid.UUID(tank_id), Alert.status == "active"))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 1. Écart de volume (déclaration créée APRÈS une détection déjà en base) —
#    déclenchement automatique au moment de la déclaration.
# ---------------------------------------------------------------------------
async def test_declaration_creation_triggers_discrepancy_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    async with AsyncSessionLocal() as db:
        db.add(DeliveryDetected(
            tankId=uuid.UUID(tank_id), startTime=datetime(2026, 3, 1, 8, 15), startHeightMm=500,
            endTime=datetime(2026, 3, 1, 8, 45), endHeightMm=1500, volumeLiters=4500,
        ))
        await db.commit()

    res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-03-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["reconciledWithId"] is not None

    alerts = await _active_alerts(tank_id)
    assert any(a.type == "delivery_discrepancy" for a in alerts), alerts


# ---------------------------------------------------------------------------
# 2. Rapprochement dans le sens inverse : la déclaration existe déjà
#    ("pending"), la détection arrive ensuite et doit la retrouver.
# ---------------------------------------------------------------------------
async def test_detection_creation_resolves_pending_declaration(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id, sensor_id = await _setup_tank_with_sensor_and_calibration(
        client, headers, zylo_liquid_organization["id"], suffix
    )
    base = datetime(2026, 3, 5, 10, 0, 0)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": base.isoformat(), "declaredVolumeLiters": 10875},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]
    assert declaration_res.json()["reconciledWithId"] is not None  # pending, aucune détection pour l'instant

    await _insert_delivery_measurement_series(sensor_id, base)
    async with AsyncSessionLocal() as db:
        created = await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))
    assert len(created) == 1  # 16075 - 5200 = 10875 L détectés, exactement le volume déclaré

    list_res = await client.get(f"/api/v1/zylo-liquid/delivery-declarations?stationId={station_id}", headers=headers)
    declaration_row = next(r for r in list_res.json()["data"] if r["id"] == declaration_id)
    reconciliation_res = await client.get(f"/api/v1/zylo-liquid/reconciliation-records?subjectId={declaration_id}", headers=headers)
    latest = next(r for r in reconciliation_res.json()["data"] if r["id"] == declaration_row["reconciledWithId"])
    assert latest["status"] == "matched", latest

    # Aucune alerte "livraison sauvage" : la détection a bien trouvé sa déclaration.
    alerts = await _active_alerts(tank_id)
    assert not any(a.type == "delivery_undeclared" for a in alerts), alerts


# ---------------------------------------------------------------------------
# 3. Livraison physique détectée, aucune déclaration nulle part — le cas
#    explicitement désigné comme le plus important à signaler.
# ---------------------------------------------------------------------------
async def test_detection_without_any_declaration_creates_undeclared_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    _station_id, _fuel_product_id, tank_id, sensor_id = await _setup_tank_with_sensor_and_calibration(
        client, headers, zylo_liquid_organization["id"], suffix
    )
    await _insert_delivery_measurement_series(sensor_id, datetime(2026, 3, 10, 9, 0, 0))

    async with AsyncSessionLocal() as db:
        created = await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))
    assert len(created) == 1

    alerts = await _active_alerts(tank_id)
    assert any(a.type == "delivery_undeclared" for a in alerts), alerts


# ---------------------------------------------------------------------------
# 4. Déclaration ancienne toujours sans détection — alerte plus légère,
#    jamais confondue avec un écart avéré.
# ---------------------------------------------------------------------------
async def test_stale_pending_declaration_creates_lighter_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    old_event_at = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": old_event_at, "declaredVolumeLiters": 5000},
        headers=headers,
    )
    assert res.status_code == 201, res.text

    alerts = await _active_alerts(tank_id)
    assert any(a.type == "delivery_declaration_pending" for a in alerts), alerts
    assert not any(a.type == "delivery_discrepancy" for a in alerts), alerts


# ---------------------------------------------------------------------------
# 5. Contrôle négatif : un rapprochement réussi (matched) ne crée aucune
#    alerte — jamais de spam sur le cas nominal.
# ---------------------------------------------------------------------------
async def test_matched_delivery_creates_no_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    async with AsyncSessionLocal() as db:
        db.add(DeliveryDetected(
            tankId=uuid.UUID(tank_id), startTime=datetime(2026, 3, 15, 8, 15), startHeightMm=500,
            endTime=datetime(2026, 3, 15, 8, 45), endHeightMm=1500, volumeLiters=5030,
        ))
        await db.commit()

    res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-03-15T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    assert res.status_code == 201, res.text

    alerts = await _active_alerts(tank_id)
    assert alerts == []
