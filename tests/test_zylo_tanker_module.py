"""Vérifie que le squelette du module Zylo Tanker (catalogue,
activation, garde `require_module_active`) fonctionne de bout en bout
avant toute fonctionnalité métier réelle — même esprit que
`tests/test_modules.py::test_module_lifecycle_blocks_and_allows_access`
pour zylo_liquid."""

from httpx import AsyncClient


async def _headers(registered_user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_zylo_tanker_ping_blocked_then_allowed_after_activation(client: AsyncClient, registered_user: dict, organization: dict):
    headers = await _headers(registered_user, organization)
    org_id = organization["id"]

    res = await client.get("/api/v1/zylo-tanker/ping", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"

    res = await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_tanker"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "active"

    res = await client.get("/api/v1/zylo-tanker/ping", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body == {"module": "zylo_tanker", "status": "ok", "organizationId": org_id}
