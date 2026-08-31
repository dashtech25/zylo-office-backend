from httpx import AsyncClient


async def _headers(registered_user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_module_lifecycle_blocks_and_allows_access(client: AsyncClient, registered_user: dict, organization: dict):
    headers = await _headers(registered_user, organization)
    org_id = organization["id"]

    res = await client.get(f"/api/v1/modules/organizations/{org_id}/zylo-liquid/protected-demo", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"

    res = await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "active"

    res = await client.get(f"/api/v1/modules/organizations/{org_id}/zylo-liquid/protected-demo", headers=headers)
    assert res.status_code == 200

    res = await client.post(f"/api/v1/modules/organizations/{org_id}/deactivate", json={"moduleCode": "zylo_liquid"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "inactive"

    res = await client.get(f"/api/v1/modules/organizations/{org_id}/zylo-liquid/protected-demo", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"


async def test_list_modules_is_paginated(client: AsyncClient, registered_user: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.get("/api/v1/modules?limit=1&offset=0", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "data" in body and "meta" in body
    assert body["meta"]["limit"] == 1
    assert len(body["data"]) <= 1
