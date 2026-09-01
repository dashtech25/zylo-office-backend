import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import TankMeasurement
from app.modules.zylo_liquid.service import run_delivery_detection_for_tank
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank_with_sensor_and_calibration(client: AsyncClient, headers: dict, organization_id: str, station_code: str) -> tuple[str, str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Liv", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 30000,
            "tankHeightMm": 2000,
            "newFuelProductName": f"Produit {station_code}",
            "newFuelProductCode": station_code[:10],
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 445, "volumeLiters": 5200}, {"heightMm": 1293, "volumeLiters": 16075}]},
        headers=headers,
    )
    serial = f"XM_LIV_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return station_id, tank_id, sensor_id


async def _insert_delivery_measurement_series(sensor_id: int) -> None:
    """Rejoue le scénario exact de nouveau-zylo-liquid/Point 8 §8.5/§8.8 :
    hausse de 445mm à 1298mm puis stabilisation à 1293mm."""
    base = datetime(2026, 8, 1, 10, 0, 0)
    series = [
        (base, 445),
        (base + timedelta(minutes=5), 490),
        (base + timedelta(minutes=10), 601),
        (base + timedelta(minutes=15), 748),
        (base + timedelta(hours=1, minutes=10), 1240),
        (base + timedelta(hours=1, minutes=15), 1298),
        (base + timedelta(hours=1, minutes=20), 1295),
        (base + timedelta(hours=1, minutes=25), 1293),
        (base + timedelta(hours=1, minutes=30), 1293),
    ]
    async with AsyncSessionLocal() as db:
        for measured_at, height in series:
            db.add(
                TankMeasurement(
                    hkSensorId=sensor_id,
                    hkDeviceSerial="XM_LIV",
                    hkUnit="mm",
                    measuredAt=measured_at,
                    rawValue=height,
                    insertedAt=datetime.utcnow(),
                    isCorrection=False,
                )
            )
        await db.commit()


async def test_delivery_detection_and_read_full_scenario(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Niveau 3 — scénario d'intégration de bout en bout (Point 4) : une
    série de mesures réelles produit une livraison détectée avec le bon
    volume, consultable via l'API."""
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, sensor_id = await _create_tank_with_sensor_and_calibration(
        client, headers, zylo_liquid_organization["id"], "LIV-01"
    )
    await _insert_delivery_measurement_series(sensor_id)

    async with AsyncSessionLocal() as db:
        created = await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))
    assert len(created) == 1

    list_res = await client.get(f"/api/v1/zylo-liquid/deliveries?tankId={tank_id}", headers=headers)
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["meta"]["total"] == 1
    delivery = body["data"][0]
    assert delivery["stationId"] == station_id
    assert delivery["startHeightMm"] == 445
    assert delivery["endHeightMm"] == 1293
    assert delivery["volumeLiters"] == 10875  # calibration(1293)-calibration(445), Point 8.6

    get_res = await client.get(f"/api/v1/zylo-liquid/deliveries/{delivery['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == delivery["id"]


async def test_delivery_detection_is_idempotent(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor_and_calibration(client, headers, zylo_liquid_organization["id"], "LIV-02")
    await _insert_delivery_measurement_series(sensor_id)

    async with AsyncSessionLocal() as db:
        first_run = await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))
    assert len(first_run) == 1

    async with AsyncSessionLocal() as db:
        second_run = await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))
    assert len(second_run) == 0  # déjà détectée, jamais dupliquée

    list_res = await client.get(f"/api/v1/zylo-liquid/deliveries?tankId={tank_id}", headers=headers)
    assert list_res.json()["meta"]["total"] == 1


async def test_list_deliveries_filtered_by_date_range(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor_and_calibration(client, headers, zylo_liquid_organization["id"], "LIV-03")
    await _insert_delivery_measurement_series(sensor_id)
    async with AsyncSessionLocal() as db:
        await run_delivery_detection_for_tank(db, uuid.UUID(tank_id))

    res = await client.get(
        f"/api/v1/zylo-liquid/deliveries?tankId={tank_id}&fromDate=2026-09-01T00:00:00&toDate=2026-09-02T00:00:00", headers=headers
    )
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 0  # hors plage (livraison le 2026-08-01)


async def test_list_deliveries_invalid_date_range_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get(
        "/api/v1/zylo-liquid/deliveries?fromDate=2026-08-02T00:00:00&toDate=2026-08-01T00:00:00", headers=headers
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_date_range"


async def test_get_delivery_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/deliveries/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "delivery_not_found"


async def test_list_deliveries_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/deliveries", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
