import uuid

from httpx import AsyncClient


async def test_create_plan_and_list(client: AsyncClient, registered_user: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"

    res = await client.post(
        "/api/v1/billing/plans",
        json={"moduleCode": "zylo_liquid", "code": plan_code, "name": "Test Plan", "priceCents": 1000, "currency": "XAF", "periodDays": 30},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["code"] == plan_code

    res = await client.get("/api/v1/billing/plans", headers=headers)
    assert res.status_code == 200
    assert any(p["code"] == plan_code for p in res.json())


async def test_trial_subscription_lifecycle(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"

    await client.post(
        "/api/v1/billing/plans",
        json={"moduleCode": "zylo_liquid", "code": plan_code, "name": "Test Plan", "priceCents": 1000, "currency": "XAF", "periodDays": 30},
        headers=headers,
    )

    res = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions", json={"planCode": plan_code}, headers=headers
    )
    assert res.status_code == 201
    assert res.json()["status"] == "trial"

    duplicate = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions", json={"planCode": plan_code}, headers=headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "subscription_already_active"
