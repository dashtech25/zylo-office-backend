from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_create_and_get_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Douala Akwa", "code": "DLA-01", "cityId": test_city["id"], "address": "Rue X", "phone": "699000000"},
        headers=headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Station Douala Akwa"
    assert body["status"] == "active"
    assert body["activeTankCount"] == 0
    assert body["organizationId"] == zylo_liquid_organization["id"]

    get_res = await client.get(f"/api/v1/zylo-liquid/stations/{body['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == body["id"]


async def test_create_station_with_unknown_city_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station X", "code": "X-01", "cityId": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "city_not_found"


async def test_create_station_duplicate_code_same_organization_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station A", "code": "ST-01"}, headers=headers)
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station B", "code": "ST-01"}, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "station_code_already_used"


async def test_list_stations_is_paginated_and_isolated(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Liste", "code": "LST-01"}, headers=headers)

    res = await client.get("/api/v1/zylo-liquid/stations", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["code"] == "LST-01"


async def test_update_station_cannot_change_status(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    create_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Patch", "code": "PATCH-01"}, headers=headers)
    station_id = create_res.json()["id"]

    patch_res = await client.patch(f"/api/v1/zylo-liquid/stations/{station_id}", json={"name": "Nouveau nom", "phone": "690000000"}, headers=headers)
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["name"] == "Nouveau nom"
    assert body["phone"] == "690000000"
    assert body["status"] == "active"  # PATCH n'accepte pas 'status' (UpdateStationRequest ne l'expose pas)


async def test_deactivate_and_reactivate_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    create_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Cycle", "code": "CYCLE-01"}, headers=headers)
    station_id = create_res.json()["id"]

    deactivate_res = await client.post(f"/api/v1/zylo-liquid/stations/{station_id}/deactivate", headers=headers)
    assert deactivate_res.status_code == 200
    assert deactivate_res.json()["status"] == "inactive"

    conflict_res = await client.post(f"/api/v1/zylo-liquid/stations/{station_id}/deactivate", headers=headers)
    assert conflict_res.status_code == 409
    assert conflict_res.json()["error"]["code"] == "station_already_inactive"

    reactivate_res = await client.post(f"/api/v1/zylo-liquid/stations/{station_id}/reactivate", headers=headers)
    assert reactivate_res.status_code == 200
    assert reactivate_res.json()["status"] == "active"

    conflict_res_2 = await client.post(f"/api/v1/zylo-liquid/stations/{station_id}/reactivate", headers=headers)
    assert conflict_res_2.status_code == 409
    assert conflict_res_2.json()["error"]["code"] == "station_already_active"

    get_res = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}", headers=headers)
    assert get_res.status_code == 200  # désactivation ne supprime rien, toujours consultable


async def test_station_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/stations/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "station_not_found"


async def test_create_station_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Y", "code": "Y-01"}, headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"


async def test_closed_weekdays_roundtrip_and_validation(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """`closedWeekdays` (mission « amélioration zylo liquid », page de
    station.docx) — CSV normalisé (dédoublonné, trié) de jours ISO
    1..7, NULL explicite pour rouvrir tous les jours."""
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Fermeture", "code": "FRM-01", "closedWeekdays": "7,6,7"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    station_id = res.json()["id"]
    assert res.json()["closedWeekdays"] == "6,7"  # dédoublonné + trié

    invalid = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Invalide", "code": "FRM-02", "closedWeekdays": "0,8"},
        headers=headers,
    )
    assert invalid.status_code == 422

    clear_res = await client.patch(
        f"/api/v1/zylo-liquid/stations/{station_id}", json={"closedWeekdays": None}, headers=headers
    )
    assert clear_res.status_code == 200, clear_res.text
    assert clear_res.json()["closedWeekdays"] is None
