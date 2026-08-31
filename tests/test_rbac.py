from httpx import AsyncClient

from tests.conftest import unique_email


async def test_owner_has_access_to_own_organization(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get(f"/api/v1/organizations/{organization['id']}/protected-demo", headers=headers)
    assert res.status_code == 200
    assert res.json()["permission"] == "identity.organization.manage"


async def test_other_user_without_role_is_denied(client: AsyncClient, organization: dict):
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Outsider"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    outsider_token = login.json()["accessToken"]

    headers = {"Authorization": f"Bearer {outsider_token}", "X-Organization-Id": organization["id"]}
    res = await client.get(f"/api/v1/organizations/{organization['id']}/protected-demo", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"


async def test_missing_organization_header_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.get(f"/api/v1/organizations/{organization['id']}/protected-demo", headers=headers)
    assert res.status_code == 422  # X-Organization-Id est un header requis
