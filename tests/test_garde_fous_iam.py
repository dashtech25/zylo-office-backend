"""Garde-fous IAM (T-019) : dernier propriétaire, deny sur propriétaire, comptes inactifs.

Intention : chaque garde-fou refuse AVANT toute écriture, et un test échoue si
la garde est retirée. Un compte désactivé ou supprimé n'est plus authentifié (401).
Le deny individuel sur un propriétaire reste permis : les tests RBAC l'exigent (§5.4).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.rbac.models import Role
from tests.test_module_assignment import _add_member, _h, _new_user, _set_status


async def _role_proprietaire(org_id: str) -> str:
    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.organizationId == uuid.UUID(org_id), Role.code == "owner", Role.moduleCode.is_(None)))
        ).scalar_one()
        return str(role.id)


async def _assignment_proprietaire(client: AsyncClient, owner: dict, org_id: str, user_id: str) -> str:
    membres = await client.get(f"/api/v1/rbac/organizations/{org_id}/members", headers=_h(owner["token"], org_id))
    membre = next(m for m in membres.json() if m["userId"] == user_id)
    return next(r["assignmentId"] for r in membre["roles"] if r["code"] == "owner" or r.get("roleCode") == "owner")


async def test_dernier_proprietaire_ne_peut_pas_etre_retire(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    owner = {"id": (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"})).json()["id"],
             "token": registered_user["accessToken"]}
    assignment = await _assignment_proprietaire(client, owner, org_id, owner["id"])
    res = await client.delete(f"/api/v1/rbac/organizations/{org_id}/user-roles/{assignment}", headers=_h(owner["token"], org_id))
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "last_owner"


async def test_avec_deux_proprietaires_le_retrait_est_accepte(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    owner = {"id": (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"})).json()["id"],
             "token": registered_user["accessToken"]}
    second = await _new_user(client, "Second propriétaire")
    await _add_member(org_id, second["id"])
    ajout = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/user-roles",
        json={"userId": second["id"], "roleId": await _role_proprietaire(org_id)},
        headers=_h(owner["token"], org_id),
    )
    assert ajout.status_code == 201, ajout.text
    assignment = await _assignment_proprietaire(client, owner, org_id, owner["id"])
    res = await client.delete(f"/api/v1/rbac/organizations/{org_id}/user-roles/{assignment}", headers=_h(owner["token"], org_id))
    assert res.status_code in (200, 204), res.text


async def test_compte_desactive_recoit_401(client: AsyncClient, registered_user: dict, organization: dict):
    membre = await _new_user(client, "Compte à désactiver")
    await _set_status(membre["id"], "suspended")
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {membre['token']}"})
    assert res.status_code == 401


async def test_utilisateur_supprime_recoit_401(client: AsyncClient, registered_user: dict, organization: dict):
    from datetime import datetime, timezone

    membre = await _new_user(client, "Compte supprimé")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uuid.UUID(membre["id"]))
        user.deletedAt = datetime.now(timezone.utc)
        await db.commit()
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {membre['token']}"})
    assert res.status_code == 401
