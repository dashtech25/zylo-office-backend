import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import TankMeasurement
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank_with_sensor(client: AsyncClient, headers: dict, organization_id: str, station_code: str) -> tuple[str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Mes", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
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
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    serial = f"XM_MES_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return tank_id, sensor_id


async def _insert_measurement(sensor_id: int, measured_at: datetime, raw_value: float, is_correction: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            TankMeasurement(
                hkSensorId=sensor_id,
                hkDeviceSerial="XM_MES",
                hkUnit="mm",
                measuredAt=measured_at,
                rawValue=raw_value,
                insertedAt=datetime.utcnow(),
                isCorrection=is_correction,
            )
        )
        await db.commit()


async def test_list_measurements_ordered_by_measured_at_with_volume(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MES-01")

    base = datetime(2026, 8, 1, 8, 0, 0)
    await _insert_measurement(sensor_id, base + timedelta(hours=2), 1000)
    await _insert_measurement(sensor_id, base, 500)
    await _insert_measurement(sensor_id, base + timedelta(hours=1), 750)

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 3
    heights = [m["rawValue"] for m in body["data"]]
    assert heights == [500, 750, 1000]  # trié par measuredAt croissant
    assert body["data"][0]["volumeLiters"] == 10000  # calibration linéaire 0->0, 2000->40000 : 500mm -> 10000L


async def test_list_measurements_filtered_by_date_range(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MES-02")

    await _insert_measurement(sensor_id, datetime(2026, 1, 1, 8, 0, 0), 100)
    await _insert_measurement(sensor_id, datetime(2026, 6, 1, 8, 0, 0), 200)

    res = await client.get(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements?fromDate=2026-05-01T00:00:00&toDate=2026-07-01T00:00:00", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["rawValue"] == 200


async def test_list_measurements_invalid_date_range_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MES-03")

    res = await client.get(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements?fromDate=2026-07-01T00:00:00&toDate=2026-01-01T00:00:00", headers=headers
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_date_range"


async def test_list_measurements_no_sensor_ever_mapped_is_empty(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Mes4", "code": "MES-04"}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 1000,
            "tankHeightMm": 100,
            "newFuelProductName": "Produit MES4",
            "newFuelProductCode": "MES-04",
            "heightAlarmMm": 90,
            "heightAlertMm": 80,
            "lowAlarmMm": 10,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 0


async def test_list_measurements_survives_sensor_replacement(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Un remplacement de sonde (clôture + nouvelle association) ne doit pas
    faire disparaître l'historique de mesures déjà collecté par l'ancienne
    sonde (issue #37)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id, old_sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MES-05")
    await _insert_measurement(old_sensor_id, datetime(2026, 1, 1, 8, 0, 0), 100)

    list_res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements?limit=100", headers=headers)
    mapping_id = None
    map_list = await client.get(f"/api/v1/zylo-liquid/tank-sensor-mappings?tankId={tank_id}", headers=headers)
    mapping_id = map_list.json()["data"][0]["id"]
    await client.post(f"/api/v1/zylo-liquid/tank-sensor-mappings/{mapping_id}/close", headers=headers)

    new_serial = f"XM_MES05_new_{uuid.uuid4().hex[:6]}"
    new_sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], new_serial, "product_level")
    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": new_serial, "measurementType": "product_level"},
        headers=headers,
    )
    await _insert_measurement(new_sensor_id, datetime(2026, 2, 1, 8, 0, 0), 200)

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/measurements", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 2  # les deux mesures, ancienne et nouvelle sonde


async def test_list_measurements_tank_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/measurements", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"


async def test_list_measurements_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/measurements", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
