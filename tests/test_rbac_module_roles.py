"""Rôles et permissions PAR MODULE (T-018).

Intention : prouver, sur la vraie base de test, que
- un utilisateur reçoit un rôle propre à chaque module (commercial en CRM,
  lecture seule en Stock) et que ces droits ne se mélangent pas ;
- un rôle de module ne peut pas contenir une permission d'un autre module ;
- rien n'est accordé hors organisation, sans appartenance, module inactif,
  ni par élévation de privilège ;
- le backfill des rôles existants est explicite, rejouable et sans changement
  de droits ; la migration est réversible sans perte des autres données.
Chaque scénario d'autorisation est vérifié à la fois par le moteur (fonction
centrale) et par HTTP quand une route existe.
"""

import asyncio
import os
import re
import uuid

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES as ZL_DEFAULT_ROLES
from app.modules_registry.service import get_or_create_module
from app.rbac.module_backfill import backfill_module_roles
from app.rbac.module_rights import require_module_permission, user_has_module_permission
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.service import get_or_create_permission
from app.shared.permissions import GEO_READ
from tests.conftest import unique_email

PWD = "TestPassword123!"
CRM_READ = "crm.contact.read"
CRM_CREATE = "crm.contact.create"
CRM_UPDATE = "crm.contact.update"
STOCK_READ = "stock.item.read"
STOCK_UPDATE = "stock.item.update"


def _h(token: str, org_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}


async def _ensure_catalog() -> None:
    """Modules CRM et Stock (exemples de la demande) avec leurs permissions de test.
    Idempotent : get_or_create partout."""
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, "crm", "CRM (test)", "Module de test T-018.")
        await get_or_create_module(db, "stock", "Stock (test)", "Module de test T-018.")
        for code, module_code in [
            (CRM_READ, "crm"),
            (CRM_CREATE, "crm"),
            (CRM_UPDATE, "crm"),
            (STOCK_READ, "stock"),
            (STOCK_UPDATE, "stock"),
        ]:
            await get_or_create_permission(db, code, module_code, code)
        await db.commit()


async def _new_user(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": PWD, "fullName": "Membre T-018"})
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": PWD})).json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _add_member(org_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(org_id), userId=uuid.UUID(user_id)))
        await db.commit()


async def _activate(client: AsyncClient, owner: dict, org_id: str, module_code: str) -> None:
    res = await client.post(
        f"/api/v1/modules/organizations/{org_id}/activate",
        json={"moduleCode": module_code},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 200, res.text


async def _deactivate(client: AsyncClient, owner: dict, org_id: str, module_code: str) -> None:
    res = await client.post(
        f"/api/v1/modules/organizations/{org_id}/deactivate",
        json={"moduleCode": module_code},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 200, res.text


async def _module_role(client: AsyncClient, owner: dict, org_id: str, module_code: str, code: str, perms: list[str]) -> dict:
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles",
        json={"moduleCode": module_code, "code": code, "name": code, "permissionCodes": perms},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _assign(client: AsyncClient, granter: dict, org_id: str, user_id: str, role_id: str):
    return await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles/assignments",
        json={"userId": user_id, "roleId": role_id},
        headers=_h(granter["token"], org_id),
    )


async def _allowed(user_id: str, org_id: str, module_code: str, perm: str) -> bool:
    async with AsyncSessionLocal() as db:
        return await user_has_module_permission(db, uuid.UUID(user_id), uuid.UUID(org_id), module_code, perm)


async def _rights(client: AsyncClient, viewer: dict, org_id: str, user_id: str) -> dict:
    res = await client.get(
        f"/api/v1/rbac/organizations/{org_id}/users/{user_id}/module-rights",
        headers=_h(viewer["token"], org_id),
    )
    assert res.status_code == 200, res.text
    return {item["moduleCode"]: item for item in res.json()}


@pytest.fixture
async def crm_stock_org(client: AsyncClient, registered_user: dict, organization: dict):
    """Organisation du propriétaire avec les modules CRM et Stock activés."""
    await _ensure_catalog()
    owner = {"id": None, "token": registered_user["accessToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner['token']}"})
    owner["id"] = me.json()["id"]
    await _activate(client, owner, organization["id"], "crm")
    await _activate(client, owner, organization["id"], "stock")
    return {"org": organization, "owner": owner}


# --- Affectation par module, droits différents selon le module -------------------------


async def test_user_gets_different_role_per_module(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])

    commercial = await _module_role(client, owner, org_id, "crm", "crm_commercial", [CRM_READ, CRM_CREATE])
    lecture = await _module_role(client, owner, org_id, "stock", "stock_lecture", [STOCK_READ, GEO_READ])

    assert (await _assign(client, owner, org_id, user["id"], commercial["id"])).status_code == 201
    assert (await _assign(client, owner, org_id, user["id"], lecture["id"])).status_code == 201

    # Commercial en CRM : créer oui. Lecture seule en Stock : lire oui, modifier non.
    assert await _allowed(user["id"], org_id, "crm", CRM_CREATE) is True
    assert await _allowed(user["id"], org_id, "stock", STOCK_READ) is True
    assert await _allowed(user["id"], org_id, "stock", STOCK_UPDATE) is False
    # Aucun accès croisé : une permission CRM n'est jamais valable pour le module Stock.
    assert await _allowed(user["id"], org_id, "stock", CRM_READ) is False
    assert await _allowed(user["id"], org_id, "crm", STOCK_READ) is False

    rights = await _rights(client, owner, org_id, user["id"])
    assert rights["crm"]["active"] is True
    assert rights["crm"]["permissionCodes"] == sorted([CRM_READ, CRM_CREATE])
    assert [r["code"] for r in rights["crm"]["roles"]] == ["crm_commercial"]
    assert rights["stock"]["permissionCodes"] == [STOCK_READ]
    assert [r["code"] for r in rights["stock"]["roles"]] == ["stock_lecture"]
    # Le socle partagé est listé à part, jamais sous un module.
    assert rights["shared"]["permissionCodes"] == [GEO_READ]


async def test_module_role_cannot_contain_permission_of_another_module(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles",
        json={"moduleCode": "stock", "code": "stock_melange", "name": "mélangé", "permissionCodes": [STOCK_READ, CRM_READ]},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "permission_module_mismatch"

    # Le même rôle ne doit pas pouvoir être élargi par l'API standard de mise à jour des permissions.
    role = await _module_role(client, owner, org_id, "stock", "stock_pur", [STOCK_READ])
    res = await client.put(
        f"/api/v1/rbac/organizations/{org_id}/roles/{role['id']}/permissions",
        json={"permissionCodes": [STOCK_READ, CRM_READ]},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "permission_module_mismatch"


async def test_shared_permission_is_accepted_in_a_module_role(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    role = await _module_role(client, crm_stock_org["owner"], org_id, "stock", "stock_geo", [STOCK_READ, GEO_READ])
    assert role["moduleCode"] == "stock"


async def test_only_one_role_per_module_for_the_same_user(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    first = await _module_role(client, owner, org_id, "crm", "crm_premier", [CRM_READ])
    second = await _module_role(client, owner, org_id, "crm", "crm_second", [CRM_CREATE])
    assert (await _assign(client, owner, org_id, user["id"], first["id"])).status_code == 201
    res = await _assign(client, owner, org_id, user["id"], second["id"])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "module_role_already_assigned"


# --- Refus : appartenance, cross-organisation, module inactif, élévation -----------------


async def test_assignment_refused_for_non_member(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    outsider = await _new_user(client)
    role = await _module_role(client, crm_stock_org["owner"], org_id, "crm", "crm_nonmembre", [CRM_READ])
    res = await _assign(client, crm_stock_org["owner"], org_id, outsider["id"], role["id"])
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "user_not_member"
    assert await _allowed(outsider["id"], org_id, "crm", CRM_READ) is False


async def test_cross_organization_role_and_member_are_refused(client: AsyncClient, crm_stock_org: dict):
    org_a = crm_stock_org["org"]["id"]
    owner_a = crm_stock_org["owner"]
    # Organisation B, propriétaire distinct, rôle de module défini dans B.
    other = await _new_user(client)
    org_b_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org B", "slug": f"org-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {other['token']}"},
    )
    org_b = org_b_res.json()["id"]
    await _activate(client, {"id": other["id"], "token": other["token"]}, org_b, "crm")
    role_b = await _module_role(client, {"id": other["id"], "token": other["token"]}, org_b, "crm", "crm_b", [CRM_READ])

    # Le propriétaire de A ne peut ni affecter le rôle de B dans A...
    member = await _new_user(client)
    await _add_member(org_a, member["id"])
    res = await _assign(client, owner_a, org_a, member["id"], role_b["id"])
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "role_not_found"

    # ... ni utiliser le chemin de A avec l'en-tête de B (défaut IAM-001 : refusé ici).
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_a}/module-roles/assignments",
        json={"userId": member["id"], "roleId": role_b["id"]},
        headers=_h(other["token"], org_b),
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "organization_mismatch"

    # Une affectation faite dans A n'ouvre aucun droit dans B.
    role_a = await _module_role(client, owner_a, org_a, "crm", "crm_a", [CRM_READ])
    assert (await _assign(client, owner_a, org_a, member["id"], role_a["id"])).status_code == 201
    assert await _allowed(member["id"], org_b, "crm", CRM_READ) is False
    rights_in_b = await client.get(
        f"/api/v1/rbac/organizations/{org_b}/users/{member['id']}/module-rights",
        headers=_h(other["token"], org_b),
    )
    assert rights_in_b.status_code == 404
    assert rights_in_b.json()["error"]["code"] == "user_not_member"


async def test_module_role_refused_when_module_inactive(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    role = await _module_role(client, owner, org_id, "crm", "crm_inactif", [CRM_READ])
    await _deactivate(client, owner, org_id, "crm")

    res = await _assign(client, owner, org_id, user["id"], role["id"])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "module_not_active"


async def test_inactive_module_blocks_even_with_an_assigned_role(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    role = await _module_role(client, owner, org_id, "crm", "crm_bloque", [CRM_READ])
    assert (await _assign(client, owner, org_id, user["id"], role["id"])).status_code == 201
    assert await _allowed(user["id"], org_id, "crm", CRM_READ) is True

    await _deactivate(client, owner, org_id, "crm")
    assert await _allowed(user["id"], org_id, "crm", CRM_READ) is False
    rights = await _rights(client, owner, org_id, user["id"])
    assert rights["crm"]["active"] is False
    assert rights["crm"]["permissionCodes"] == []


async def test_privilege_escalation_is_denied_for_module_roles(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    # Gestionnaire des rôles qui ne possède que la LECTURE CRM.
    gestionnaire_res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/roles",
        json={"code": "gestionnaire_crm_lecture", "name": "Gestionnaire", "permissionCodes": [ROLE_MANAGE, CRM_READ]},
        headers=_h(owner["token"], org_id),
    )
    assert gestionnaire_res.status_code == 201, gestionnaire_res.text
    gestionnaire = await _new_user(client)
    await _add_member(org_id, gestionnaire["id"])
    await client.post(
        f"/api/v1/rbac/organizations/{org_id}/user-roles",
        json={"userId": gestionnaire["id"], "roleId": gestionnaire_res.json()["id"]},
        headers=_h(owner["token"], org_id),
    )
    commercial = await _module_role(client, owner, org_id, "crm", "crm_createur", [CRM_READ, CRM_CREATE])
    lecture = await _module_role(client, owner, org_id, "crm", "crm_lecteur_seul", [CRM_READ])
    target = await _new_user(client)
    await _add_member(org_id, target["id"])

    # Il ne peut pas donner un droit de création qu'il ne possède pas.
    res = await _assign(client, gestionnaire, org_id, target["id"], commercial["id"])
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "privilege_escalation_denied"
    assert await _allowed(target["id"], org_id, "crm", CRM_CREATE) is False

    # Il peut donner ce qu'il possède.
    assert (await _assign(client, gestionnaire, org_id, target["id"], lecture["id"])).status_code == 201


# --- Résolution centralisée : deny prioritaire, refus par défaut ------------------------


async def test_deny_overrides_module_role_and_default_is_refusal(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])

    # Sans rôle : refus par défaut, y compris pour une permission inconnue.
    assert await _allowed(user["id"], org_id, "crm", CRM_READ) is False
    assert await _allowed(user["id"], org_id, "crm", "crm.inconnu.read") is False

    role = await _module_role(client, owner, org_id, "crm", "crm_refus", [CRM_READ, CRM_CREATE])
    assert (await _assign(client, owner, org_id, user["id"], role["id"])).status_code == 201
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/grants",
        json={"userId": user["id"], "permissionCode": CRM_CREATE, "effect": "deny"},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 201, res.text

    assert await _allowed(user["id"], org_id, "crm", CRM_READ) is True
    assert await _allowed(user["id"], org_id, "crm", CRM_CREATE) is False
    rights = await _rights(client, owner, org_id, user["id"])
    assert rights["crm"]["permissionCodes"] == [CRM_READ]


async def test_user_can_read_own_rights_but_not_others_without_role_manage(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    other = await _new_user(client)
    await _add_member(org_id, other["id"])

    own = await client.get(f"/api/v1/rbac/organizations/{org_id}/users/{user['id']}/module-rights", headers=_h(user["token"], org_id))
    assert own.status_code == 200
    peek = await client.get(f"/api/v1/rbac/organizations/{org_id}/users/{other['id']}/module-rights", headers=_h(user["token"], org_id))
    assert peek.status_code == 403


async def test_unassign_removes_module_rights_and_refuses_transverse_assignment(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    role = await _module_role(client, owner, org_id, "crm", "crm_retirable", [CRM_READ])
    assignment = (await _assign(client, owner, org_id, user["id"], role["id"])).json()

    res = await client.delete(
        f"/api/v1/rbac/organizations/{org_id}/module-roles/assignments/{assignment['assignmentId']}",
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 204
    assert await _allowed(user["id"], org_id, "crm", CRM_READ) is False

    # Le rôle propriétaire est transverse : il ne se retire pas par l'API des rôles de module.
    owner_role = (await client.get(f"/api/v1/rbac/organizations/{org_id}/roles", headers=_h(owner["token"], org_id))).json()
    owner_role_id = next(r["id"] for r in owner_role if r["code"] == "owner")
    owner_assign = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles/assignments",
        json={"userId": user["id"], "roleId": owner_role_id},
        headers=_h(owner["token"], org_id),
    )
    assert owner_assign.status_code == 422
    assert owner_assign.json()["error"]["code"] == "role_not_module_role"


async def test_require_module_permission_dependency_denies_other_module(client: AsyncClient, crm_stock_org: dict):
    """La dépendance de route applique la même règle que la fonction centrale."""
    org_id = crm_stock_org["org"]["id"]
    owner = crm_stock_org["owner"]
    user = await _new_user(client)
    await _add_member(org_id, user["id"])
    role = await _module_role(client, owner, org_id, "stock", "stock_dependance", [STOCK_READ])
    assert (await _assign(client, owner, org_id, user["id"], role["id"])).status_code == 201

    async with AsyncSessionLocal() as db:
        allowed_guard = require_module_permission("stock", STOCK_READ)
        await allowed_guard(
            current_user=type("U", (), {"id": uuid.UUID(user["id"])})(),
            organization_id=uuid.UUID(org_id),
            db=db,
        )
        denied_guard = require_module_permission("crm", STOCK_READ)
        with pytest.raises(Exception) as excinfo:
            await denied_guard(
                current_user=type("U", (), {"id": uuid.UUID(user["id"])})(),
                organization_id=uuid.UUID(org_id),
                db=db,
            )
        assert getattr(excinfo.value, "status_code", None) == 403


async def test_module_role_creation_validates_permission_format(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles",
        json={"moduleCode": "crm", "code": "crm_format", "name": "x", "permissionCodes": ["crm contact lire"]},
        headers=_h(crm_stock_org["owner"]["token"], org_id),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "permission_code_invalid"


# --- Backfill explicite, idempotent, sans changement de droits -------------------------


async def test_backfill_attaches_legacy_default_roles_idempotently(zylo_liquid_organization: dict):
    org_id = zylo_liquid_organization["id"]
    await _ensure_catalog()
    async with AsyncSessionLocal() as db:
        # Simule des rôles créés AVANT Role.moduleCode : colonne remise à NULL.
        await db.execute(
            text('UPDATE role SET "moduleCode" = NULL WHERE "organizationId" = :org AND code LIKE \'zylo_liquid_%\''),
            {"org": uuid.UUID(org_id)},
        )
        auditor = (
            await db.execute(text('SELECT id FROM role WHERE "organizationId" = :org AND code = \'zylo_liquid_auditor\''), {"org": uuid.UUID(org_id)})
        ).scalar_one()
        crm_read = (await db.execute(text("SELECT id FROM permission WHERE code = :c"), {"c": CRM_READ})).scalar_one()
        # Rôle par défaut « pollué » : une permission d'un autre module. Il ne doit pas être rattaché.
        await db.execute(text('INSERT INTO "rolePermission" (id, "roleId", "permissionId") VALUES (:id, :r, :p)'), {"id": uuid.uuid4(), "r": auditor, "p": crm_read})
        await db.commit()

    defaults = {"zylo_liquid": [code for code, _n, _p in ZL_DEFAULT_ROLES]}
    async with AsyncSessionLocal() as db:
        dry = await backfill_module_roles(db, defaults, dry_run=True)
    dry_org = [e for e in dry["rattached"] if e["organizationId"] == org_id]
    assert {e["code"] for e in dry_org} == {code for code, _n, _p in ZL_DEFAULT_ROLES} - {"zylo_liquid_auditor"}
    async with AsyncSessionLocal() as db:
        still_null = (await db.execute(text('SELECT count(*) FROM role WHERE "organizationId" = :org AND "moduleCode" IS NOT NULL'), {"org": uuid.UUID(org_id)})).scalar_one()
    assert still_null == 0  # le dry-run ne modifie rien

    async with AsyncSessionLocal() as db:
        report = await backfill_module_roles(db, defaults)
    applied = [e for e in report["rattached"] if e["organizationId"] == org_id]
    assert {e["code"] for e in applied} == {e["code"] for e in dry_org}
    conflicts = [e for e in report["conflicts"] if e["organizationId"] == org_id]
    assert [e["code"] for e in conflicts] == ["zylo_liquid_auditor"]
    assert conflicts[0]["foreignPermissionCodes"] == [CRM_READ]

    async with AsyncSessionLocal() as db:
        module_of = dict((await db.execute(text('SELECT code, "moduleCode" FROM role WHERE "organizationId" = :org'), {"org": uuid.UUID(org_id)})).all())
    assert module_of["zylo_liquid_cashier"] == "zylo_liquid"
    assert module_of["zylo_liquid_auditor"] is None
    assert module_of["owner"] is None

    # Relancer ne change rien.
    async with AsyncSessionLocal() as db:
        again = await backfill_module_roles(db, defaults)
    assert [e for e in again["rattached"] if e["organizationId"] == org_id] == []


async def test_backfill_reports_custom_roles_without_touching_them(client: AsyncClient, crm_stock_org: dict):
    org_id = crm_stock_org["org"]["id"]
    custom = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/roles",
        json={"code": "perso_transverse", "name": "Perso", "permissionCodes": []},
        headers=_h(crm_stock_org["owner"]["token"], org_id),
    )
    assert custom.status_code == 201
    async with AsyncSessionLocal() as db:
        report = await backfill_module_roles(db, {"crm": []})
    assert any(e["code"] == "perso_transverse" for e in report["customRoles"])
    async with AsyncSessionLocal() as db:
        module_code = (await db.execute(text('SELECT "moduleCode" FROM role WHERE id = :id'), {"id": uuid.UUID(custom.json()["id"])})).scalar_one()
    assert module_code is None


def test_migration_round_trip_keeps_existing_roles():
    """Migration réversible sur la base de test uniquement : le downgrade supprime
    la colonne, le upgrade la rétablit, les lignes `role` existantes sont conservées."""
    url = os.environ["DATABASE_URL"]
    assert re.search(r"zylo_t\d{3}[a-z]?_test", url), "garde : seule une base de test jetable est autorisée"
    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini"))

    async def column_exists() -> bool:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_name = 'role' AND column_name = 'moduleCode'"
                        )
                    )
                ).scalar_one() == 1
        finally:
            await engine.dispose()

    async def role_count() -> int:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text('SELECT count(*) FROM role'))).scalar_one()
        finally:
            await engine.dispose()

    assert asyncio.run(column_exists()) is True
    before = asyncio.run(role_count())
    command.downgrade(cfg, "e2f3a4b5c6d7")
    assert asyncio.run(column_exists()) is False
    assert asyncio.run(role_count()) == before
    command.upgrade(cfg, "head")
    assert asyncio.run(column_exists()) is True
    assert asyncio.run(role_count()) == before
