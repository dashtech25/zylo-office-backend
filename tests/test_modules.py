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


async def test_activating_module_grants_its_permissions_to_owner(client: AsyncClient, registered_user: dict, organization: dict):
    """L'activation d'un module doit rendre ses permissions immédiatement
    utilisables par le owner — sans endpoint RBAC HTTP pour les attribuer
    manuellement, ce serait sinon un module activé mais inutilisable
    (constat fait à la construction de l'endpoint 1 de Zylo Liquid, issue #23)."""
    headers = await _headers(registered_user, organization)
    org_id = organization["id"]

    res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Super", "code": "SP"}, headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"

    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Super", "code": "SP"}, headers=headers)
    assert res.status_code == 201


async def test_list_modules_is_paginated(client: AsyncClient, registered_user: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.get("/api/v1/modules?limit=1&offset=0", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "data" in body and "meta" in body
    assert body["meta"]["limit"] == 1
    assert len(body["data"]) <= 1
