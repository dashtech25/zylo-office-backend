import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import TankMeasurement
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank_with_sensor(client: AsyncClient, headers: dict, organization_id: str, station_code: str) -> tuple[str, str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Snap", "code": station_code}, headers=headers)
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
    serial = f"XM_SNAP_{uuid.uuid4().hex[:6]}"
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
                hkDeviceSerial="XM_SNAP",
                hkUnit="mm",
                measuredAt=measured_at,
                rawValue=raw_value,
                insertedAt=datetime.utcnow(),
                isCorrection=False,
            )
        )
        await db.commit()


async def test_snapshot_uses_latest_measurement_before_or_equal_to_date(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "SNAP-01")

    await _insert_measurement(sensor_id, datetime(2026, 1, 1, 8, 0, 0), 500)  # -> 10000 L
    await _insert_measurement(sensor_id, datetime(2026, 6, 1, 8, 0, 0), 1000)  # -> 20000 L (postérieure)

    res = await client.get(
        "/api/v1/zylo-liquid/network/snapshot?at=2026-03-01T00:00:00", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["totalVolumeLiters"] == 10000  # jamais la mesure postérieure (1000mm)


async def test_snapshot_excludes_tank_without_measurement_before_date(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "SNAP-02")
    await _insert_measurement(sensor_id, datetime(2026, 6, 1, 8, 0, 0), 1000)

    res = await client.get("/api/v1/zylo-liquid/network/snapshot?at=2026-01-01T00:00:00", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["products"] == []
    assert body["totalVolumeLiters"] == 0  # jamais un zéro comptabilisé -> totaux vides


async def test_snapshot_future_date_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    future = (datetime.utcnow() + timedelta(days=365)).isoformat()
    res = await client.get(f"/api/v1/zylo-liquid/network/snapshot?at={future}", headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "snapshot_date_in_future"


async def test_snapshot_requires_at_parameter(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/network/snapshot", headers=headers)
    assert res.status_code == 422  # paramètre obligatoire (Point 2 §5.4)


async def test_snapshot_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/network/snapshot?at=2026-01-01T00:00:00", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
