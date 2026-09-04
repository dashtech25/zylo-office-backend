import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient

from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_station_and_tank(
    client: AsyncClient, headers: dict, station_code: str, thermal_expansion_coefficient: float | None = None
) -> tuple[str, str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station CS", "code": station_code}, headers=headers)
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
    calib_res = await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": h, "volumeLiters": h * 20} for h in [0, 1000, 1050, 1100, 2000]]},
        headers=headers,
    )
    assert calib_res.status_code == 200, calib_res.text
    return station_id, tank_id, fuel_product_id


async def test_current_state_not_configured_without_sensor(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _ = await _create_station_and_tank(client, headers, "CS-01")

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sensorStatus"] == "not_configured"
    assert body["heightMm"] is None
    assert body["volumeLiters"] is None
    assert body["volumeNotCalculableReason"] == "no_active_sensor"


async def test_current_state_with_measurement_computes_volume(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _ = await _create_station_and_tank(client, headers, "CS-02")

    serial = f"XM_CS02_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201

    from app.core.database import AsyncSessionLocal
    from app.modules.zylo_liquid.models import HolykellDeviceRegistry
    from sqlalchemy import select, update
    import asyncio

    async def set_last_value():
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(HolykellDeviceRegistry)
                .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
                .values(lastValue=1073, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
            )
            await db.commit()

    await set_last_value()

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sensorStatus"] == "online"
    assert body["heightMm"] == 1073
    assert body["volumeLiters"] == pytest.approx(21460, abs=1)  # calibration linéaire h*20 -> 1073*20
    assert body["lastMeasurementAt"] is not None


async def test_current_state_with_water_and_thermal_correction(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _ = await _create_station_and_tank(client, headers, "CS-06", thermal_expansion_coefficient=0.00085)

    from app.core.database import AsyncSessionLocal
    from app.modules.zylo_liquid.models import HolykellDeviceRegistry
    from sqlalchemy import update

    async def set_last_value(serial_suffix: str, measurement_type: str, value: float) -> int:
        serial = f"XM_CS06_{measurement_type}_{uuid.uuid4().hex[:6]}"
        sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, measurement_type)
        map_res = await client.post(
            "/api/v1/zylo-liquid/tank-sensor-mappings",
            json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": measurement_type},
            headers=headers,
        )
        assert map_res.status_code == 201, map_res.text
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(HolykellDeviceRegistry)
                .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
                .values(lastValue=value, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
            )
            await db.commit()
        return sensor_id

    await set_last_value("h", "product_level", 1073)  # V_brut = 21460 (calibration h*20)
    await set_last_value("w", "water_level", 50)  # V_eau = 1000 (calibration h*20)
    await set_last_value("t", "temperature", 35)

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["waterHeightMm"] == 50
    assert body["waterVolumeLiters"] == pytest.approx(1000, abs=1)
    assert body["volumeLiters"] == pytest.approx(21460 - 1000, abs=1)  # V_carburant = V_brut - V_eau
    assert body["temperatureC"] == 35
    # V_15 = V_net * [1 - 0.00085 * (35-15)] = 20460 * 0.983
    assert body["volumeLiters15C"] == pytest.approx(20460 * 0.983, abs=1)
    assert body["emptyVolumeLiters"] == pytest.approx(40000 - 21460, abs=1)


async def test_current_state_offline_sensor(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _ = await _create_station_and_tank(client, headers, "CS-03")

    serial = f"XM_CS03_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")
    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )

    from app.core.database import AsyncSessionLocal
    from app.modules.zylo_liquid.models import HolykellDeviceRegistry
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId == sensor_id).values(lastValue=500, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=0)
        )
        await db.commit()

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    assert res.json()["sensorStatus"] == "offline"


async def test_current_state_without_calibration_table(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station CS4", "code": "CS-04"}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "newFuelProductName": "Produit CS4",
            "newFuelProductCode": "CS-04",
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]

    serial = f"XM_CS04_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")
    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    from app.core.database import AsyncSessionLocal
    from app.modules.zylo_liquid.models import HolykellDeviceRegistry
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId == sensor_id).values(lastValue=500, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
        )
        await db.commit()

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["heightMm"] == 500
    assert body["volumeLiters"] is None
    assert body["volumeNotCalculableReason"] == "no_calibration_table"


async def test_current_state_tank_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/current-state", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"


async def test_station_current_state_lists_all_active_tanks(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, _ = await _create_station_and_tank(client, headers, "CS-05")

    res = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["stationId"] == station_id
    assert len(body["tanks"]) == 1
    assert body["tanks"][0]["tankId"] == tank_id


async def test_station_current_state_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/stations/00000000-0000-0000-0000-000000000000/current-state", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "station_not_found"


async def test_current_state_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/current-state", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
