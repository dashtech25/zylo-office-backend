import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import HolykellDeviceRegistry, TankMeasurement
from app.modules.zylo_liquid.service import run_alert_evaluation_for_tank, run_leak_test_for_tank
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank_with_sensor(
    client: AsyncClient, headers: dict, organization_id: str, station_code: str,
    height_alarm=1900, height_alert=1800, low_alarm=200, water_alarm=200,
) -> tuple[str, str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Alerte", "code": station_code}, headers=headers)
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
            "heightAlarmMm": height_alarm,
            "heightAlertMm": height_alert,
            "lowAlarmMm": low_alarm,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]
    if water_alarm != 200:
        await client.patch(f"/api/v1/zylo-liquid/tanks/{tank_id}", json={"alertWaterMaxMm": water_alarm}, headers=headers)
    serial = f"XM_ALERT_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return station_id, tank_id, sensor_id


async def _set_last_value(sensor_id: int, value: float, status: int = 1) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
            .values(lastValue=value, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=status)
        )
        await db.commit()


async def test_low_level_alert_full_scenario(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Niveau 3 — scénario complet : une mesure sous le seuil bas produit
    une alerte, consultable et résoluble via l'API."""
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-01")
    await _set_last_value(sensor_id, 195)  # Point 13 §13.5 : H_net=195mm, Low_alarm=200mm

    async with AsyncSessionLocal() as db:
        created = await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))
    assert len(created) == 1
    assert created[0].type == "level_low"

    list_res = await client.get(f"/api/v1/zylo-liquid/alerts?tankId={tank_id}", headers=headers)
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["meta"]["total"] == 1
    alert = body["data"][0]
    assert alert["stationId"] == station_id
    assert alert["type"] == "level_low"
    assert alert["status"] == "active"

    resolve_res = await client.patch(f"/api/v1/zylo-liquid/alerts/{alert['id']}", json={"resolutionNote": "Livraison programmée"}, headers=headers)
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "resolved"
    assert resolve_res.json()["resolvedAt"] is not None

    already_resolved = await client.patch(f"/api/v1/zylo-liquid/alerts/{alert['id']}", json={}, headers=headers)
    assert already_resolved.status_code == 409
    assert already_resolved.json()["error"]["code"] == "alert_already_resolved"


async def test_alert_evaluation_does_not_duplicate_active_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-02")
    await _set_last_value(sensor_id, 195)

    async with AsyncSessionLocal() as db:
        first = await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))
        second = await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))
    assert len(first) == 1
    assert len(second) == 0  # déjà une alerte active du même type, jamais dupliquée


async def test_alert_evaluation_no_trigger_within_normal_range(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-03")
    await _set_last_value(sensor_id, 1000)

    async with AsyncSessionLocal() as db:
        created = await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))
    assert created == []


async def test_sensor_offline_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-04")
    await _set_last_value(sensor_id, 1000, status=0)

    async with AsyncSessionLocal() as db:
        created = await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))
    assert len(created) == 1
    assert created[0].type == "sensor_offline"


async def test_leak_test_anomaly_creates_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Le déclencheur fuite (Point 2 chapitre 4) crée une alerte via le
    même mécanisme que l'endpoint 11, sans logique dupliquée."""
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-05")
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    start = datetime(2026, 8, 1, 22, 0, 0)
    end = start + timedelta(hours=8)
    async with AsyncSessionLocal() as db:
        db.add(TankMeasurement(hkSensorId=sensor_id, hkDeviceSerial="XM_ALT", hkUnit="mm", measuredAt=start, rawValue=1000, insertedAt=datetime.utcnow(), isCorrection=False))
        db.add(TankMeasurement(hkSensorId=sensor_id, hkDeviceSerial="XM_ALT", hkUnit="mm", measuredAt=end, rawValue=999.8, insertedAt=datetime.utcnow(), isCorrection=False))
        await db.commit()

    async with AsyncSessionLocal() as db:
        await run_leak_test_for_tank(db, uuid.UUID(tank_id), start, end)

    res = await client.get(f"/api/v1/zylo-liquid/alerts?tankId={tank_id}&type=leak", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 1


async def test_list_alerts_filtered_by_type_and_status(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "ALT-06")
    await _set_last_value(sensor_id, 195)
    async with AsyncSessionLocal() as db:
        await run_alert_evaluation_for_tank(db, uuid.UUID(tank_id))

    res_type = await client.get(f"/api/v1/zylo-liquid/alerts?tankId={tank_id}&type=level_low", headers=headers)
    assert res_type.json()["meta"]["total"] == 1
    res_status = await client.get(f"/api/v1/zylo-liquid/alerts?tankId={tank_id}&status=resolved", headers=headers)
    assert res_status.json()["meta"]["total"] == 0


async def test_get_alert_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/alerts/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "alert_not_found"


async def test_list_alerts_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/alerts", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
