import uuid

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

    await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)

    res = await client.get(f"/api/v1/modules/organizations/{org_id}", headers=headers)
    zylo_liquid = next(item for item in res.json() if item["moduleCode"] == "zylo_liquid")
    assert zylo_liquid["status"] == "active"
    assert zylo_liquid["activatedAt"] is not None


async def test_list_organization_modules_is_forbidden_for_a_non_member(client: AsyncClient, organization: dict):
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Outsider"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}

    res = await client.get(f"/api/v1/modules/organizations/{organization['id']}", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "not_organization_member"


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
