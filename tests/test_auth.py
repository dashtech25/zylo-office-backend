from httpx import AsyncClient

from tests.conftest import unique_email


async def test_register_then_login(client: AsyncClient):
    email = unique_email()
    password = "TestPassword123!"

    res = await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Alice"})
    assert res.status_code == 201
    assert res.json()["email"] == email

    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    body = res.json()
    assert "accessToken" in body
    assert "refreshToken" in body


async def test_register_duplicate_email_rejected(client: AsyncClient):
    email = unique_email()
    payload = {"email": email, "password": "TestPassword123!", "fullName": "Bob"}
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "email_already_used"


async def test_login_wrong_password_rejected(client: AsyncClient):
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!", "fullName": "Carl"})

    res = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


async def test_me_requires_valid_token(client: AsyncClient, registered_user: dict):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401

    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"})
    assert res.status_code == 200
    assert res.json()["email"] == registered_user["email"]


async def test_refresh_rotates_and_invalidates_old_token(client: AsyncClient, registered_user: dict):
    old_refresh = registered_user["refreshToken"]

    res = await client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh})
    assert res.status_code == 200
    new_tokens = res.json()
    assert new_tokens["refreshToken"] != old_refresh

    reuse = await client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "invalid_refresh_token"


async def test_logout_then_refresh_fails(client: AsyncClient, registered_user: dict):
    refresh_token = registered_user["refreshToken"]

    res = await client.post("/api/v1/auth/logout", json={"refreshToken": refresh_token})
    assert res.status_code == 204

    res = await client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert res.status_code == 401
