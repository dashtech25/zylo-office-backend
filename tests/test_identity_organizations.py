import uuid

from httpx import AsyncClient


async def test_list_my_organizations_returns_only_organizations_the_user_belongs_to(
    client: AsyncClient, registered_user: dict, organization: dict
):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}

    res = await client.get("/api/v1/organizations", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert [org["id"] for org in body] == [organization["id"]]


async def test_current_organization_requires_valid_membership_and_returns_profile(
    client: AsyncClient, registered_user: dict, organization: dict
):
    headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": organization["id"],
    }

    res = await client.get("/api/v1/organizations/current", headers=headers)

    assert res.status_code == 200
    assert res.json() == organization


async def test_current_organization_rejects_a_non_member(
    client: AsyncClient, registered_user: dict
):
    headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": str(uuid.uuid4()),
    }

    res = await client.get("/api/v1/organizations/current", headers=headers)

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"
    assert "request_id" in res.json()


async def test_list_my_organizations_is_empty_for_a_user_without_any_organization(client: AsyncClient):
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Lone User"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}

    res = await client.get("/api/v1/organizations", headers=headers)
    assert res.status_code == 200
    assert res.json() == []
