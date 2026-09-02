import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.modules.zylo_liquid.dev_seed import seed_demo_network


def _headers(registered_user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _seed(organization: dict, city_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        owner = (
            await db.execute(
                select(OrganizationUser).where(OrganizationUser.organizationId == uuid.UUID(organization["id"]))
            )
        ).scalar_one()
        result = await seed_demo_network(db, uuid.UUID(organization["id"]), owner.userId, uuid.UUID(city_id))
        await db.commit()
        return result


async def test_seed_demo_network_populates_a_realistic_network(
    client: AsyncClient, registered_user: dict, organization: dict, test_city: dict
):
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    result = await _seed(organization, test_city["id"])
    assert result["skipped"] is False
    assert result["stationCount"] == 5
    assert result["tankCount"] == 7

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["totalStationCount"] > 0
    assert body["totalVolumeLiters"] > 0
    assert {p["fuelProductName"] for p in body["products"]} == {"Super", "Gasoil", "Pétrole"}

    res = await client.get("/api/v1/zylo-liquid/alerts?status=active", headers=headers)
    assert res.status_code == 200
    alert_types = {a["type"] for a in res.json()["data"]}
    assert alert_types == {"sensor_offline", "level_high", "level_low", "leak"}

    res = await client.get("/api/v1/zylo-liquid/deliveries", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 1


async def test_seed_demo_network_is_idempotent(
    client: AsyncClient, registered_user: dict, organization: dict, test_city: dict
):
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    first = await _seed(organization, test_city["id"])
    second = await _seed(organization, test_city["id"])
    assert first["skipped"] is False
    assert second == {"skipped": True, "reason": "organization_already_has_stations"}
