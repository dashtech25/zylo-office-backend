import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
import pytest

from app.billing.models import SubscriptionEntitlement
from app.core.database import AsyncSessionLocal


@pytest.mark.parametrize(
    ("entitlement_status", "subscription_status", "expected"),
    [
        ("active", "active", ("active", True)),
        ("mystery", "active", ("unknown", False)),
        ("active", "mystery", ("unknown", False)),
    ],
)
def test_explicit_unknown_entitlement_states_fail_closed(
    entitlement_status: str, subscription_status: str, expected: tuple[str, bool]
):
    from types import SimpleNamespace
    from app.modules_registry.service import _project_entitlement_access

    now = datetime.now(timezone.utc)
    row = (
        SimpleNamespace(status=entitlement_status, startsAt=now, endsAt=None),
        subscription_status,
    )
    assert _project_entitlement_access(row, now) == expected


def test_future_entitlement_does_not_mask_current_active_entitlement():
    from types import SimpleNamespace
    from app.modules_registry.service import _project_entitlement_access, _select_effective_entitlement

    now = datetime.now(timezone.utc)
    current = (
        SimpleNamespace(status="active", startsAt=now, endsAt=None, createdAt=now),
        "active",
    )
    future_start = now.replace(year=now.year + 1)
    future = (
        SimpleNamespace(status="inactive", startsAt=future_start, endsAt=None, createdAt=future_start),
        "active",
    )
    selected = _select_effective_entitlement([future, current], now)
    assert selected is current
    assert _project_entitlement_access(selected, now) == ("active", True)


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


async def test_explicit_active_entitlement_allows_activation_of_uninstalled_module(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    from app.billing import service as billing_service

    headers = await _headers(registered_user, organization)
    plan_code = f"entitled-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await billing_service.get_or_create_plan(db, "zylo_liquid", plan_code, "Entitled plan", 1000, "XAF", 30)
    subscription_response = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions",
        json={"planCode": plan_code}, headers=headers,
    )
    assert subscription_response.status_code == 201
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(SubscriptionEntitlement(
            organizationId=uuid.UUID(organization["id"]),
            subscriptionId=uuid.UUID(subscription_response.json()["id"]),
            moduleCode="zylo_liquid", entitlementCode="module.access",
            status="active", startsAt=now,
        ))
        await db.commit()

    # Entitlement grants access but does not install the module by itself.
    modules = await client.get(f"/api/v1/modules/organizations/{organization['id']}", headers=headers)
    projected = next(m for m in modules.json() if m["moduleCode"] == "zylo_liquid")
    assert projected["status"] == "inactive"
    assert projected["accessState"] == "active"
    assert projected["canActivate"] is True
    assert projected["canOpen"] is False
    activated = await client.post(
        f"/api/v1/modules/organizations/{organization['id']}/activate",
        json={"moduleCode": "zylo_liquid"}, headers=headers,
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    modules = await client.get(f"/api/v1/modules/organizations/{organization['id']}", headers=headers)
    assert next(m for m in modules.json() if m["moduleCode"] == "zylo_liquid")["canOpen"] is True


@pytest.mark.parametrize("entitlement_status", ["inactive", "expired", "blocked"])
async def test_explicit_blocked_entitlement_denies_module_open_and_activation(
    client: AsyncClient, registered_user: dict, organization: dict, entitlement_status: str,
):
    from app.billing import service as billing_service

    headers = await _headers(registered_user, organization)
    plan_code = f"blocked-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await billing_service.get_or_create_plan(db, "zylo_liquid", plan_code, "Blocked plan", 1000, "XAF", 30)
    subscription_response = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions",
        json={"planCode": plan_code}, headers=headers,
    )
    assert subscription_response.status_code == 201
    initially_activated = await client.post(
        f"/api/v1/modules/organizations/{organization['id']}/activate",
        json={"moduleCode": "zylo_liquid"}, headers=headers,
    )
    assert initially_activated.status_code == 200
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(SubscriptionEntitlement(
            organizationId=uuid.UUID(organization["id"]),
            subscriptionId=uuid.UUID(subscription_response.json()["id"]),
            moduleCode="zylo_liquid", entitlementCode="module.access",
            status=entitlement_status, startsAt=now,
        ))
        await db.commit()
    opened = await client.get(
        f"/api/v1/modules/organizations/{organization['id']}/zylo-liquid/protected-demo",
        headers=headers,
    )
    assert opened.status_code == 403
    assert opened.json()["error"]["code"] == "module_entitlement_unavailable"
    activated = await client.post(
        f"/api/v1/modules/organizations/{organization['id']}/activate",
        json={"moduleCode": "zylo_liquid"}, headers=headers,
    )
    assert activated.status_code == 403
    assert activated.json()["error"]["code"] == "module_entitlement_unavailable"
    modules = await client.get(f"/api/v1/modules/organizations/{organization['id']}", headers=headers)
    projected = next(m for m in modules.json() if m["moduleCode"] == "zylo_liquid")
    assert projected["status"] == "active"  # Installation and entitlement remain separate.
    assert projected["accessState"] == entitlement_status
    assert projected["canActivate"] is False
    assert projected["canOpen"] is False


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


async def test_list_organization_modules_defaults_to_inactive_and_reflects_activation(
    client: AsyncClient, registered_user: dict, organization: dict
):
    headers = await _headers(registered_user, organization)
    org_id = organization["id"]

    res = await client.get(f"/api/v1/modules/organizations/{org_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body) > 0
    zylo_liquid = next(item for item in body if item["moduleCode"] == "zylo_liquid")
    assert zylo_liquid["status"] == "inactive"
    assert zylo_liquid["activatedAt"] is None
    assert zylo_liquid["accessState"] == "not_configured"
    assert zylo_liquid["canActivate"] is True  # Legacy compatibility; not a paid-plan assertion.
    assert zylo_liquid["canOpen"] is False

    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    res = await client.get(f"/api/v1/modules/organizations/{org_id}", headers=headers)
    zylo_liquid = next(item for item in res.json() if item["moduleCode"] == "zylo_liquid")
    assert zylo_liquid["status"] == "active"
    assert zylo_liquid["activatedAt"] is not None
    assert zylo_liquid["canOpen"] is True


async def test_list_organization_modules_is_forbidden_for_a_non_member(client: AsyncClient, organization: dict):
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Outsider"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}

    res = await client.get(f"/api/v1/modules/organizations/{organization['id']}", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"


async def test_backfill_grants_permissions_added_after_module_activation(client: AsyncClient, registered_user: dict, organization: dict):
    """Bug réel découvert par un test E2E navigateur (processus-double-
    sources-verite, Phase 8) : une organisation qui avait activé zylo_liquid
    AVANT l'ajout de nouvelles permissions au module (ex. la couche
    déclarative) ne les recevait jamais — `grant_module_permissions_to_owner`
    ne s'exécute qu'à l'activation, jamais rejoué après coup. Vérifie que le
    backfill comble ce manque, sans toucher aux permissions déjà accordées."""
    from app.core.database import AsyncSessionLocal
    from app.identity.models import User
    from app.modules_registry.service import backfill_active_module_permissions_for_owners
    from app.rbac.models import Permission, Role, RolePermission
    from app.rbac.service import get_or_create_permission
    from sqlalchemy import select

    headers = await _headers(registered_user, organization)
    org_id = organization["id"]
    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    # Simule une permission ajoutée au module APRÈS cette activation (comme
    # les permissions de la Phase 8, ajoutées longtemps après l'activation
    # initiale de zylo_liquid par des organisations déjà existantes).
    fake_permission_code = f"zyloLiquid.testFutureFeature.{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, fake_permission_code, "zylo_liquid", "Permission de test ajoutée après coup.")
        await db.commit()

        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        owner_role = (await db.execute(select(Role).where(Role.organizationId == org_id, Role.code == "owner"))).scalar_one()
        permission = (await db.execute(select(Permission).where(Permission.code == fake_permission_code))).scalar_one()

        # Avant le backfill : le owner n'a pas cette permission (créée après son activation du module).
        has_it_before = (
            await db.execute(select(RolePermission).where(RolePermission.roleId == owner_role.id, RolePermission.permissionId == permission.id))
        ).scalar_one_or_none()
        assert has_it_before is None

        await backfill_active_module_permissions_for_owners(db)

        has_it_after = (
            await db.execute(select(RolePermission).where(RolePermission.roleId == owner_role.id, RolePermission.permissionId == permission.id))
        ).scalar_one_or_none()
        assert has_it_after is not None

    # Idempotent — un second passage ne doit ni échouer ni dupliquer.
    async with AsyncSessionLocal() as db:
        await backfill_active_module_permissions_for_owners(db)
        count = (
            await db.execute(select(RolePermission).where(RolePermission.roleId == owner_role.id, RolePermission.permissionId == permission.id))
        ).scalars().all()
        assert len(count) == 1
