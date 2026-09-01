import uuid
from datetime import datetime

from httpx import AsyncClient

from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_measured_tank(
    client: AsyncClient, headers: dict, organization_id: str, station_code: str, fuel_code: str, height_mm: float
) -> None:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station NS", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "newFuelProductName": f"Produit {fuel_code}",
            "newFuelProductCode": fuel_code,
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
    serial = f"XM_NS_{fuel_code}_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
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
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
            .values(lastValue=height_mm, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
        )
        await db.commit()


async def test_network_summary_aggregates_by_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    org_id = zylo_liquid_organization["id"]
    await _create_measured_tank(client, headers, org_id, "NS-01", "SP-NS", 1000)  # -> 20000 L
    await _create_measured_tank(client, headers, org_id, "NS-02", "GO-NS", 500)  # -> 10000 L

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["totalStationCount"] == 2
    assert body["totalTankCount"] == 2
    assert body["totalVolumeLiters"] == 30000
    volumes_by_product = {p["fuelProductName"]: p["totalVolumeLiters"] for p in body["products"]}
    assert volumes_by_product["Produit SP-NS"] == 20000
    assert volumes_by_product["Produit GO-NS"] == 10000


async def test_network_summary_excludes_tank_without_calculable_volume(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station NS3", "code": "NS-03"}, headers=headers)
    station_id = st_res.json()["id"]
    await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve sans capteur",
            "capacityLiters": 1000,
            "tankHeightMm": 100,
            "newFuelProductName": "Produit NS3",
            "newFuelProductCode": "NS-03",
            "heightAlarmMm": 90,
            "heightAlertMm": 80,
            "lowAlarmMm": 10,
        },
        headers=headers,
    )

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["products"] == []  # cuve non configurée -> exclue, jamais comptée comme 0
    assert body["totalVolumeLiters"] == 0
    assert body["totalTankCount"] == 0


async def test_network_summary_is_isolated_per_organization(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    await _create_measured_tank(client, headers, zylo_liquid_organization["id"], "NS-04", "SP-NS4", 1000)

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    assert res.json()["totalVolumeLiters"] == 20000


async def test_network_summary_with_period_is_not_supported(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get(
        "/api/v1/zylo-liquid/network/summary?fromDate=2026-01-01T00:00:00&toDate=2026-02-01T00:00:00", headers=headers
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "historical_network_summary_not_supported"


async def test_network_summary_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
