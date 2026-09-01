from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_station(client: AsyncClient, headers: dict, code: str = "STK-01") -> str:
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Tank Test", "code": code}, headers=headers)
    return res.json()["id"]


async def test_create_tank_with_existing_fuel_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers)
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Super", "code": "SP"}, headers=headers)
    fuel_product_id = fp_res.json()["id"]

    res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 3000,
            "fuelProductId": fuel_product_id,
            "heightAlarmMm": 2800,
            "heightAlertMm": 2600,
            "lowAlarmMm": 300,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["stationId"] == station_id
    assert body["fuelProductId"] == fuel_product_id
    assert body["heightAlarmMm"] == 2800
    assert body["active"] is True


async def test_create_tank_with_new_fuel_product_inline(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers, code="STK-02")

    res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 30000,
            "tankHeightMm": 2500,
            "newFuelProductName": "Gasoil",
            "newFuelProductCode": "GO",
            "heightAlarmMm": 2300,
            "heightAlertMm": 2100,
            "lowAlarmMm": 250,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    fuel_product_id = res.json()["fuelProductId"]

    fp_get = await client.get(f"/api/v1/zylo-liquid/fuel-products/{fuel_product_id}", headers=headers)
    assert fp_get.status_code == 200
    assert fp_get.json()["code"] == "GO"


async def test_create_tank_both_or_neither_fuel_product_selection_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers, code="STK-03")

    neither = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={"stationId": station_id, "tankNumber": 1, "displayName": "Cuve 1", "capacityLiters": 1000, "tankHeightMm": 100, "heightAlarmMm": 90, "heightAlertMm": 80, "lowAlarmMm": 10},
        headers=headers,
    )
    assert neither.status_code == 422
    assert neither.json()["error"]["code"] == "fuel_product_selection_invalid"


async def test_create_tank_duplicate_number_same_station_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers, code="STK-04")
    payload = {
        "stationId": station_id,
        "tankNumber": 1,
        "displayName": "Cuve 1",
        "capacityLiters": 1000,
        "tankHeightMm": 100,
        "newFuelProductName": "Petrole",
        "newFuelProductCode": "PL",
        "heightAlarmMm": 90,
        "heightAlertMm": 80,
        "lowAlarmMm": 10,
    }
    await client.post("/api/v1/zylo-liquid/tanks", json=payload, headers=headers)
    payload["newFuelProductCode"] = "PL2"
    res = await client.post("/api/v1/zylo-liquid/tanks", json=payload, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "tank_number_already_used"


async def test_create_tank_unknown_station_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": "00000000-0000-0000-0000-000000000000",
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 1000,
            "tankHeightMm": 100,
            "newFuelProductName": "Petrole",
            "newFuelProductCode": "PL",
            "heightAlarmMm": 90,
            "heightAlertMm": 80,
            "lowAlarmMm": 10,
        },
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "station_not_found"


async def test_get_and_update_and_list_tank(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers, code="STK-05")
    create_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 20000,
            "tankHeightMm": 2000,
            "newFuelProductName": "Super",
            "newFuelProductCode": "SP2",
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = create_res.json()["id"]

    get_res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}", headers=headers)
    assert get_res.status_code == 200

    patch_res = await client.patch(f"/api/v1/zylo-liquid/tanks/{tank_id}", json={"heightAlarmMm": 1950}, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["heightAlarmMm"] == 1950

    list_res = await client.get(f"/api/v1/zylo-liquid/tanks?stationId={station_id}", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["meta"]["total"] == 1


async def test_tank_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/tanks/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"


async def test_tank_of_other_organization_is_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id = await _create_station(client, headers, code="STK-06")
    create_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 5000,
            "tankHeightMm": 1000,
            "newFuelProductName": "Kerosene",
            "newFuelProductCode": "KE2",
            "heightAlarmMm": 900,
            "heightAlertMm": 800,
            "lowAlarmMm": 100,
        },
        headers=headers,
    )
    tank_id = create_res.json()["id"]

    from tests.conftest import unique_email

    other_email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": other_email, "password": "TestPassword123!", "fullName": "Other"})
    other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": "TestPassword123!"})
    other_token = other_login.json()["accessToken"]
    import uuid

    other_org_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Other Org Tank", "slug": f"other-org-tank-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    other_org = other_org_res.json()
    other_activate = await client.post(
        f"/api/v1/modules/organizations/{other_org['id']}/activate",
        json={"moduleCode": "zylo_liquid"},
        headers={"Authorization": f"Bearer {other_token}", "X-Organization-Id": other_org["id"]},
    )
    assert other_activate.status_code == 200

    other_headers = {"Authorization": f"Bearer {other_token}", "X-Organization-Id": other_org["id"]}
    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}", headers=other_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"
