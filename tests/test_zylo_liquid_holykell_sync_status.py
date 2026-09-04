import uuid
from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import HolykellAccount


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_holykell_account(organization_id: str, status: str = "success") -> str:
    async with AsyncSessionLocal() as db:
        account = HolykellAccount(
            organizationId=uuid.UUID(organization_id),
            holykellUsername="user-sync-test",
            holykellPassword="secret",
            lastSyncAt=datetime.now(timezone.utc).replace(tzinfo=None),
            lastSyncStatus=status,
            lastSyncError="Timeout h-smartlink.com" if status == "failed" else None,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return str(account.id)


async def test_get_sync_status_success(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    account_id = await _create_holykell_account(zylo_liquid_organization["id"], status="success")

    res = await client.get(f"/api/v1/zylo-liquid/holykell-accounts/{account_id}/sync-status", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["lastSyncStatus"] == "success"
    assert body["lastSyncError"] is None
    assert body["organizationId"] == zylo_liquid_organization["id"]


async def test_get_sync_status_failed(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    account_id = await _create_holykell_account(zylo_liquid_organization["id"], status="failed")

    res = await client.get(f"/api/v1/zylo-liquid/holykell-accounts/{account_id}/sync-status", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["lastSyncStatus"] == "failed"
    assert body["lastSyncError"] == "Timeout h-smartlink.com"


async def test_get_sync_status_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/holykell-accounts/00000000-0000-0000-0000-000000000000/sync-status", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "holykell_account_not_found"


async def test_get_sync_status_of_other_organization_is_not_found(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, organization: dict
):
    account_id = await _create_holykell_account(zylo_liquid_organization["id"])

    from tests.conftest import unique_email

    other_email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": other_email, "password": "TestPassword123!", "fullName": "Other"})
    other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": "TestPassword123!"})
    other_token = other_login.json()["accessToken"]
    other_org_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Other Org Sync", "slug": f"other-org-sync-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    other_org = other_org_res.json()
    activate_res = await client.post(
        f"/api/v1/modules/organizations/{other_org['id']}/activate",
        json={"moduleCode": "zylo_liquid"},
        headers={"Authorization": f"Bearer {other_token}", "X-Organization-Id": other_org["id"]},
    )
    assert activate_res.status_code == 200

    other_headers = {"Authorization": f"Bearer {other_token}", "X-Organization-Id": other_org["id"]}
    res = await client.get(f"/api/v1/zylo-liquid/holykell-accounts/{account_id}/sync-status", headers=other_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "holykell_account_not_found"


async def test_get_sync_status_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/holykell-accounts/00000000-0000-0000-0000-000000000000/sync-status", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
