import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import TankMeasurement
from app.modules.zylo_liquid.service import run_leak_test_for_tank
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank_with_product_sensor(
    client: AsyncClient, headers: dict, organization_id: str, station_code: str, thermal_expansion_coefficient: float = 0.00085
) -> tuple[str, str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Fuite", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post(
        "/api/v1/zylo-liquid/fuel-products",
        json={"name": f"Produit {station_code}", "code": station_code[:10], "thermalExpansionCoefficient": thermal_expansion_coefficient},
        headers=headers,
    )
    fuel_product_id = fp_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "fuelProductId": fuel_product_id,
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    serial = f"XM_LEAK_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return station_id, tank_id, sensor_id


async def _insert_measurement(sensor_id: int, measured_at: datetime, raw_value: float) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            TankMeasurement(
                hkSensorId=sensor_id,
                hkDeviceSerial="XM_LEAK",
                hkUnit="mm",
                measuredAt=measured_at,
                rawValue=raw_value,
                insertedAt=datetime.utcnow(),
                isCorrection=False,
            )
        )
        await db.commit()


async def test_leak_test_detects_anomaly_full_scenario(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Niveau 3 — scénario complet : une vraie perte de carburant (sans
    variation d'eau/température) produit un événement 'anomaly' avec le
    bon taux, consultable via l'API."""
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, sensor_id = await _create_tank_with_product_sensor(client, headers, zylo_liquid_organization["id"], "LEAK-01")

    start = datetime(2026, 8, 1, 22, 0, 0)
    end = start + timedelta(hours=8)
    # 1000mm -> 20000L (calibration 0-2000mm/0-40000L) ; perte de 4L sur 8h = 0.5 L/H > seuil
    await _insert_measurement(sensor_id, start, 1000)
    await _insert_measurement(sensor_id, end, 999.8)  # 999.8*20=19996L, perte de 4L/8h=0.5L/H

    async with AsyncSessionLocal() as db:
        record = await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)
    assert record.result == "anomaly"

    list_res = await client.get(f"/api/v1/zylo-liquid/leak-events?tankId={tank_id}", headers=headers)
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["meta"]["total"] == 1
    event = body["data"][0]
    assert event["stationId"] == station_id
    assert event["result"] == "anomaly"
    assert event["leakRateLph"] == 0.5

    get_res = await client.get(f"/api/v1/zylo-liquid/leak-events/{event['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == event["id"]


async def test_leak_test_below_threshold_is_normal(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_product_sensor(client, headers, zylo_liquid_organization["id"], "LEAK-02")

    start = datetime(2026, 8, 2, 22, 0, 0)
    end = start + timedelta(hours=24)
    # 1000mm -> 20000L ; perte de 5L/24h = 0.208 L/H < seuil
    await _insert_measurement(sensor_id, start, 1000)
    await _insert_measurement(sensor_id, end, 999.75)

    async with AsyncSessionLocal() as db:
        record = await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)
    assert record.result == "normal"


async def test_leak_test_is_idempotent(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_product_sensor(client, headers, zylo_liquid_organization["id"], "LEAK-03")
    start = datetime(2026, 8, 3, 22, 0, 0)
    end = start + timedelta(hours=8)
    await _insert_measurement(sensor_id, start, 1000)
    await _insert_measurement(sensor_id, end, 999.8)

    async with AsyncSessionLocal() as db:
        first = await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)
        second = await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)
    assert first.id == second.id  # même fenêtre -> même enregistrement, jamais dupliqué


async def test_leak_test_missing_measurement_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _ = await _create_tank_with_product_sensor(client, headers, zylo_liquid_organization["id"], "LEAK-04")
    start = datetime(2026, 8, 4, 22, 0, 0)
    end = start + timedelta(hours=8)

    async with AsyncSessionLocal() as db:
        try:
            await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)
            assert False, "devrait lever AppError"
        except Exception as exc:
            assert getattr(exc, "code", None) == "measurement_not_found_for_window"


async def test_list_leak_events_filtered_by_result(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_product_sensor(client, headers, zylo_liquid_organization["id"], "LEAK-05")
    start = datetime(2026, 8, 5, 22, 0, 0)
    end = start + timedelta(hours=8)
    await _insert_measurement(sensor_id, start, 1000)
    await _insert_measurement(sensor_id, end, 999.8)
    async with AsyncSessionLocal() as db:
        await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)

    res_anomaly = await client.get(f"/api/v1/zylo-liquid/leak-events?tankId={tank_id}&result=anomaly", headers=headers)
    assert res_anomaly.json()["meta"]["total"] == 1
    res_normal = await client.get(f"/api/v1/zylo-liquid/leak-events?tankId={tank_id}&result=normal", headers=headers)
    assert res_normal.json()["meta"]["total"] == 0


async def test_get_leak_event_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/leak-events/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "leak_event_not_found"


async def test_list_leak_events_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/leak-events", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
