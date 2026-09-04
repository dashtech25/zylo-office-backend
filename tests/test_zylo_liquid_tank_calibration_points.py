from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank(client: AsyncClient, headers: dict, station_code: str, tank_height_mm: float = 3000) -> str:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Calib", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve",
            "capacityLiters": 40000,
            "tankHeightMm": tank_height_mm,
            "newFuelProductName": f"Produit {station_code}",
            "newFuelProductCode": station_code[:10],
            "heightAlarmMm": tank_height_mm - 200,
            "heightAlertMm": tank_height_mm - 400,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    return tank_res.json()["id"]


async def test_replace_and_get_calibration_points(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-01")

    put_res = await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 1000, "volumeLiters": 15000}, {"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 32000}]},
        headers=headers,
    )
    assert put_res.status_code == 200, put_res.text
    body = put_res.json()
    assert body["pointCount"] == 3
    assert [p["heightMm"] for p in body["points"]] == [0, 1000, 2000]  # trié par hauteur croissante

    get_res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points", headers=headers)
    assert get_res.status_code == 200
    assert len(get_res.json()) == 3


async def test_get_calibration_points_empty_is_not_an_error(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-02")

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points", headers=headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_replace_calibration_points_height_exceeds_tank_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-03", tank_height_mm=2000)

    res = await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2500, "volumeLiters": 40000}]},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "calibration_height_exceeds_tank"


async def test_replace_calibration_points_non_monotonic_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-04")

    res = await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 1000, "volumeLiters": 20000}, {"heightMm": 2000, "volumeLiters": 15000}]},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "calibration_table_not_monotonic"


async def test_replace_calibration_points_empty_list_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-05")

    res = await client.put(f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points", json={"points": []}, headers=headers)
    assert res.status_code == 422  # validation Pydantic (min_length=1)


async def test_replace_calibration_points_is_a_full_replacement(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "CAL-06")

    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 1000, "volumeLiters": 15000}]},
        headers=headers,
    )
    second_res = await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 500, "volumeLiters": 8000}]},
        headers=headers,
    )
    assert second_res.status_code == 200
    assert second_res.json()["pointCount"] == 2  # l'ancienne table (2 points) a été remplacée, pas fusionnée

    get_res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points", headers=headers)
    heights = [p["heightMm"] for p in get_res.json()]
    assert heights == [0, 500]


async def test_replace_calibration_points_unknown_tank_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.put(
        "/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}]},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"


async def test_replace_calibration_points_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.put(
        "/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}]},
        headers=headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
