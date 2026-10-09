"""Affectation d'un utilisateur à un module, avec ses droits propres (T-022).

Intention : prouver, sur la vraie base de test et via HTTP, que
- l'administrateur liste les membres d'un module et leur rôle, puis affecte,
  change et retire le rôle d'un membre ; un seul rôle par module ;
- les droits d'un même utilisateur diffèrent d'un module à l'autre ;
- chaque garde-fou refuse AVANT toute écriture : non-membre, compte inactif,
  module inactif, rôle d'un autre module, rôle transverse (propriétaire),
  élévation de privilège, dernier administrateur du module ;
- la prévisualisation montre les droits avant/après sans rien écrire ;
- chaque changement effectif laisse une trace dans le journal d'audit.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.modules.zylo_liquid.permissions import STATION_MANAGE, STATION_READ
from app.modules.zylo_tanker.permissions import VESSEL_MANAGE, VESSEL_READ
from app.modules_registry.service import get_or_create_module
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.module_rights import user_has_module_permission
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

PWD = "TestPassword123!"
LIQUID = "zylo_liquid"
TANKER = "zylo_tanker"
CRM = "crm"
CRM_READ = "crm.contact.read"
CRM_MANAGE = "crm.contact.manage"


def _h(token: str, org_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}


async def _ensure_crm() -> None:
    """Module de test sans implémentation : sert à prouver que le mécanisme est générique."""
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, CRM, "CRM (test)", "Module de test T-022.")
        await get_or_create_permission(db, CRM_READ, CRM, CRM_READ)
        await get_or_create_permission(db, CRM_MANAGE, CRM, CRM_MANAGE)
        await db.commit()


async def _new_user(client: AsyncClient, nom: str = "Membre T-022") -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": PWD, "fullName": nom})
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": PWD})).json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _add_member(org_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(org_id), userId=uuid.UUID(user_id)))
        await db.commit()


async def _set_status(user_id: str, status: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        user.status = status
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


async def _role(client: AsyncClient, owner: dict, org_id: str, module_code: str, code: str, perms: list[str]) -> dict:
    res = await client.post(
        f"/api/v1/rbac/organizations/{org_id}/module-roles",
        json={"moduleCode": module_code, "code": code, "name": code, "permissionCodes": perms},
        headers=_h(owner["token"], org_id),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _put(client: AsyncClient, actor: dict, org_id: str, module_code: str, user_id: str, role_id: str):
    return await client.put(
        f"/api/v1/rbac/organizations/{org_id}/modules/{module_code}/users/{user_id}/role",
        json={"roleId": role_id},
        headers=_h(actor["token"], org_id),
    )


async def _delete(client: AsyncClient, actor: dict, org_id: str, module_code: str, user_id: str):
    return await client.delete(
        f"/api/v1/rbac/organizations/{org_id}/modules/{module_code}/users/{user_id}/role",
        headers=_h(actor["token"], org_id),
    )


async def _preview(client: AsyncClient, actor: dict, org_id: str, module_code: str, user_id: str, role_id: str | None = None):
    params = {"roleId": role_id} if role_id else {}
    return await client.get(
        f"/api/v1/rbac/organizations/{org_id}/modules/{module_code}/users/{user_id}/role-preview",
        params=params,
        headers=_h(actor["token"], org_id),
    )


async def _allowed(user_id: str, org_id: str, module_code: str, perm: str) -> bool:
    async with AsyncSessionLocal() as db:
        return await user_has_module_permission(db, uuid.UUID(user_id), uuid.UUID(org_id), module_code, perm)


async def _module_assignments(org_id: str, user_id: str, module_code: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count(UserRole.id))
                .join(Role, Role.id == UserRole.roleId)
                .where(UserRole.organizationId == uuid.UUID(org_id), UserRole.userId == uuid.UUID(user_id), Role.moduleCode == module_code)
            )
        ).scalar_one()


async def _audit_actions(org_id: str) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text('SELECT action FROM "auditLog" WHERE "organizationId" = :org'),
            {"org": uuid.UUID(org_id)},
        )
        return [r[0] for r in rows.all()]


async def _grant_transverse_role(org_id: str, user_id: str, permission_code: str) -> None:
    """Donne à un utilisateur un rôle TRANSVERSE (moduleCode NULL) portant une permission du socle.
    Sert à créer un gestionnaire qui n'a pas, par défaut, les droits qu'il veut affecter."""
    async with AsyncSessionLocal() as db:
        permission = await get_or_create_permission(db, permission_code, "rbac", permission_code)
        role = Role(organizationId=uuid.UUID(org_id), code=f"gest-{uuid.uuid4().hex[:6]}", name="Gestionnaire test", moduleCode=None)
        db.add(role)
        await db.flush()
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=uuid.UUID(user_id), organizationId=uuid.UUID(org_id), roleId=role.id, resourceType=None, resourceId=None))
        await db.commit()


@pytest.fixture
async def org_modules(client: AsyncClient, registered_user: dict, organization: dict):
    """Organisation du propriétaire, modules zylo_liquid, zylo_tanker et crm activés."""
    await _ensure_crm()
    owner = {"id": None, "token": registered_user["accessToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner['token']}"})
    owner["id"] = me.json()["id"]
    org_id = organization["id"]
    for module_code in (LIQUID, TANKER, CRM):
        await _activate(client, owner, org_id, module_code)
    return {"org": org_id, "owner": owner}


# ---------------------------------------------------------------------------
# Parcours nominal
# ---------------------------------------------------------------------------


async def test_meme_utilisateur_droits_differents_selon_le_module(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    lecteur_liquid = await _role(client, owner, org, LIQUID, "liquid_lecteur", [STATION_READ])
    gestion_tanker = await _role(client, owner, org, TANKER, "tanker_gestion", [VESSEL_READ, VESSEL_MANAGE])

    assert (await _put(client, owner, org, LIQUID, membre["id"], lecteur_liquid["id"])).status_code == 200
    assert (await _put(client, owner, org, TANKER, membre["id"], gestion_tanker["id"])).status_code == 200

    assert await _allowed(membre["id"], org, LIQUID, STATION_READ) is True
    assert await _allowed(membre["id"], org, LIQUID, STATION_MANAGE) is False
    assert await _allowed(membre["id"], org, TANKER, VESSEL_MANAGE) is True

    rights = (
        await client.get(f"/api/v1/rbac/organizations/{org}/users/{membre['id']}/module-rights", headers=_h(owner["token"], org))
    ).json()
    by_module = {item["moduleCode"]: item for item in rights}
    assert by_module[LIQUID]["permissionCodes"] == [STATION_READ]
    assert by_module[TANKER]["permissionCodes"] == sorted([VESSEL_READ, VESSEL_MANAGE])


async def test_liste_des_membres_avec_leur_role_sur_le_module(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    affecte = await _new_user(client, "Affecté")
    await _add_member(org, affecte["id"])
    libre = await _new_user(client, "Sans rôle")
    await _add_member(org, libre["id"])
    role = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    await _put(client, owner, org, CRM, affecte["id"], role["id"])

    res = await client.get(f"/api/v1/rbac/organizations/{org}/modules/{CRM}/members", headers=_h(owner["token"], org))
    assert res.status_code == 200, res.text
    par_id = {m["userId"]: m for m in res.json()}
    assert par_id[affecte["id"]]["role"]["roleId"] == role["id"]
    assert par_id[libre["id"]]["role"] is None


async def test_changer_de_role_remplace_sans_cumul(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    lecteur = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    gestion = await _role(client, owner, org, CRM, "crm_gestion", [CRM_READ, CRM_MANAGE])

    assert (await _put(client, owner, org, CRM, membre["id"], lecteur["id"])).status_code == 200
    res = await _put(client, owner, org, CRM, membre["id"], gestion["id"])
    assert res.status_code == 200, res.text

    assert await _module_assignments(org, membre["id"], CRM) == 1
    assert await _allowed(membre["id"], org, CRM, CRM_MANAGE) is True
    actions = await _audit_actions(org)
    assert "rbac.moduleRole.change" in actions


async def test_retirer_le_role_supprime_les_droits_et_trace_l_audit(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    role = await _role(client, owner, org, TANKER, "tanker_lecteur", [VESSEL_READ])
    await _put(client, owner, org, TANKER, membre["id"], role["id"])

    assert (await _delete(client, owner, org, TANKER, membre["id"])).status_code == 204
    assert await _allowed(membre["id"], org, TANKER, VESSEL_READ) is False
    # Second retrait : rien à retirer.
    assert (await _delete(client, owner, org, TANKER, membre["id"])).status_code == 404
    actions = await _audit_actions(org)
    assert actions.count("rbac.moduleRole.assign") == 1
    assert "rbac.moduleRole.unassign" in actions


async def test_generique_meme_parcours_sur_un_module_futur(client: AsyncClient, org_modules: dict):
    """Le mécanisme ne dépend d'aucun module codé en dur : même parcours sur crm."""
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    role = await _role(client, owner, org, CRM, "crm_commercial", [CRM_READ, CRM_MANAGE])
    assert (await _put(client, owner, org, CRM, membre["id"], role["id"])).status_code == 200
    assert await _allowed(membre["id"], org, CRM, CRM_MANAGE) is True
    # Seul administrateur du module : le retrait est refusé (garde commun à tous les modules).
    assert (await _delete(client, owner, org, CRM, membre["id"])).status_code == 409
    other = await _new_user(client)
    await _add_member(org, other["id"])
    await _put(client, owner, org, CRM, other["id"], role["id"])
    assert (await _delete(client, owner, org, CRM, membre["id"])).status_code == 204


# ---------------------------------------------------------------------------
# Garde-fous : refus AVANT écriture
# ---------------------------------------------------------------------------


async def test_non_membre_refuse_sans_ecriture(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    etranger = await _new_user(client)  # jamais ajouté à l'organisation
    role = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    res = await _put(client, owner, org, CRM, etranger["id"], role["id"])
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "user_not_member"
    assert await _module_assignments(org, etranger["id"], CRM) == 0


async def test_compte_non_actif_refuse(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    suspendu = await _new_user(client)
    await _add_member(org, suspendu["id"])
    await _set_status(suspendu["id"], "suspended")
    role = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    res = await _put(client, owner, org, CRM, suspendu["id"], role["id"])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "user_not_active"
    assert await _module_assignments(org, suspendu["id"], CRM) == 0


async def test_module_inactif_refuse_et_retrait_reste_possible(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    role = await _role(client, owner, org, TANKER, "tanker_lecteur", [VESSEL_READ])
    await _put(client, owner, org, TANKER, membre["id"], role["id"])
    await _deactivate(client, owner, org, TANKER)

    other = await _new_user(client)
    await _add_member(org, other["id"])
    res = await _put(client, owner, org, TANKER, other["id"], role["id"])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "module_not_active"
    assert await _module_assignments(org, other["id"], TANKER) == 0
    # Nettoyage d'une affectation existante : toujours permis.
    assert (await _delete(client, owner, org, TANKER, membre["id"])).status_code == 204


async def test_role_d_un_autre_module_refuse(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    role_tanker = await _role(client, owner, org, TANKER, "tanker_lecteur", [VESSEL_READ])
    res = await _put(client, owner, org, CRM, membre["id"], role_tanker["id"])
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "role_module_mismatch"


async def test_role_transverse_proprietaire_refuse(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    async with AsyncSessionLocal() as db:
        transverse = Role(organizationId=uuid.UUID(org), code=f"transv-{uuid.uuid4().hex[:6]}", name="Transverse", moduleCode=None)
        db.add(transverse)
        await db.commit()
        role_id = str(transverse.id)
    res = await _put(client, owner, org, CRM, membre["id"], role_id)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "role_not_module_role"


async def test_escalade_refusee_si_le_demandeur_ne_possede_pas_la_permission(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    gestionnaire = await _new_user(client, "Gestionnaire partiel")
    await _add_member(org, gestionnaire["id"])
    await _grant_transverse_role(org, gestionnaire["id"], ROLE_MANAGE)
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    role = await _role(client, owner, org, CRM, "crm_gestion", [CRM_READ, CRM_MANAGE])

    res = await _put(client, gestionnaire, org, CRM, membre["id"], role["id"])
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "privilege_escalation_denied"
    assert await _module_assignments(org, membre["id"], CRM) == 0


async def test_dernier_administrateur_du_module_non_retirable(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    admin = await _new_user(client)
    await _add_member(org, admin["id"])
    lecteur = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    gestion = await _role(client, owner, org, CRM, "crm_gestion", [CRM_READ, CRM_MANAGE])
    await _put(client, owner, org, CRM, admin["id"], gestion["id"])

    # Seul administrateur du module : on ne peut pas le rétrograder ni le retirer.
    res = await _put(client, owner, org, CRM, admin["id"], lecteur["id"])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "last_module_admin"
    assert (await _delete(client, owner, org, CRM, admin["id"])).status_code == 409
    assert await _allowed(admin["id"], org, CRM, CRM_MANAGE) is True

    # Dès qu'un second administrateur existe, le premier peut être rétrogradé.
    second = await _new_user(client)
    await _add_member(org, second["id"])
    await _put(client, owner, org, CRM, second["id"], gestion["id"])
    assert (await _put(client, owner, org, CRM, admin["id"], lecteur["id"])).status_code == 200


async def test_preview_montre_avant_apres_sans_ecrire(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    lecteur = await _role(client, owner, org, CRM, "crm_lecteur", [CRM_READ])
    gestion = await _role(client, owner, org, CRM, "crm_gestion", [CRM_READ, CRM_MANAGE])
    await _put(client, owner, org, CRM, membre["id"], lecteur["id"])

    res = await _preview(client, owner, org, CRM, membre["id"], gestion["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["allowed"] is True and body["refusal"] is None
    assert body["gained"] == [CRM_MANAGE]
    assert body["lost"] == []
    assert body["current"]["roleId"] == lecteur["id"]
    # Rien n'a été écrit : le membre garde son rôle de lecteur.
    assert await _allowed(membre["id"], org, CRM, CRM_MANAGE) is False


async def test_preview_rapporte_le_refus_sans_le_lever(client: AsyncClient, org_modules: dict):
    org, owner = org_modules["org"], org_modules["owner"]
    gestionnaire = await _new_user(client, "Gestionnaire partiel")
    await _add_member(org, gestionnaire["id"])
    await _grant_transverse_role(org, gestionnaire["id"], ROLE_MANAGE)
    membre = await _new_user(client)
    await _add_member(org, membre["id"])
    gestion = await _role(client, owner, org, CRM, "crm_gestion", [CRM_READ, CRM_MANAGE])

    res = await _preview(client, gestionnaire, org, CRM, membre["id"], gestion["id"])
    assert res.status_code == 200, res.text
    assert res.json()["allowed"] is False
    assert res.json()["refusal"]["code"] == "privilege_escalation_denied"
