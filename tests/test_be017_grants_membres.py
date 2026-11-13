"""BE-017 : grants allow/deny par utilisateur, sur l'organisation courante.

Tests écrits d'après la définition `### BE-017` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Routes testées (non définies par la tâche, QE-SOC-04 ; forme retenue ici, calquée
sur BE-015) :
- POST   /api/v1/organizations/current/members/{userId}/grants
  corps : {"permissionCode", "effect": "allow" | "deny", "resourceType"?, "resourceId"?,
  "validUntil"?, "auditNote"?} ; crée un grant pour ce membre dans l'organisation courante.
- DELETE /api/v1/organizations/current/members/{userId}/grants/{grantId}
  révoque le grant (204). Un grant d'un autre membre ou d'une autre organisation : 404.

Permission (non définie, QE-SOC-06 ; reprise de l'existante) :
- `rbac.grant.manage` (GRANT_MANAGE), accordée au propriétaire.

Couverture : CA-1 (allow puis deny sur la même permission donne deny, QE-SOC-07),
CA-2 (403 sans permission d'administration, aucun grant créé), CA-3 (isolation : un grant
ne vise pas un membre de O2 depuis O1), CA-4 (chaque création et suppression écrit une
entrée d'audit). Plus : la révocation retire l'effet d'un allow ; une délégation sans
permission détenue est refusée ; une permission inconnue donne 404 ; un grant d'un autre
membre ne se révoque pas par ce chemin.

Les rôles et appartenances de test sont posés directement en base, comme dans
test_be015_affectation_roles.py.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserPermissionGrant, UserRole
from app.rbac.service import user_has_permission

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_GESTION_DROITS = "rbac.grant.manage"
PERMISSION_GESTION_ROLES = "rbac.role.manage"
PERMISSION_CIBLE = "organization.members.read"
ACTION_CREATION = "rbac.grant.create"
ACTION_REVOCATION = "rbac.grant.revoke"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be017-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    """Crée une organisation ; son créateur en devient propriétaire et membre."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be017-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _permission(db, code: str) -> Permission:
    """Permission par code ; créée si elle n'existe pas encore dans la base de test."""
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-017")
        db.add(permission)
        await db.flush()
    return permission


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation ; si `permissions` est non vide, lui
    attribue un rôle transverse ne contenant que ces permissions."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be017-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-017")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await _permission(db, code)
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _grants_de(organisation_id: str, utilisateur_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(UserPermissionGrant.id)).where(
                    UserPermissionGrant.organizationId == uuid.UUID(organisation_id),
                    UserPermissionGrant.userId == uuid.UUID(utilisateur_id),
                )
            )
        ) or 0


async def _permission_effective(organisation_id: str, utilisateur_id: str, code: str) -> bool:
    """Résultat réel de la résolution des droits (moteur `user_has_permission`)."""
    async with AsyncSessionLocal() as db:
        return await user_has_permission(db, uuid.UUID(utilisateur_id), uuid.UUID(organisation_id), code)


async def _nombre_audit(organisation_id: str, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.organizationId == uuid.UUID(organisation_id), AuditEvent.action == action
                )
            )
        ) or 0


def _entetes(acteur: dict, organisation_id: str) -> dict:
    return {"Authorization": acteur["authorization"], "X-Organization-Id": organisation_id}


def _url_grants(utilisateur_id: str) -> str:
    return f"/api/v1/organizations/current/members/{utilisateur_id}/grants"


async def test_be017_ca1_allow_puis_deny_sur_la_meme_permission_donne_deny(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA1")
    await _ajouter_membre(o1, membre["userId"], [])
    url = _url_grants(membre["userId"])

    allow = await client.post(url, json={"permissionCode": PERMISSION_CIBLE, "effect": "allow"}, headers=_entetes(proprietaire, o1))
    assert allow.status_code == 201, allow.text
    assert await _permission_effective(o1, membre["userId"], PERMISSION_CIBLE) is True

    deny = await client.post(url, json={"permissionCode": PERMISSION_CIBLE, "effect": "deny"}, headers=_entetes(proprietaire, o1))
    assert deny.status_code == 201, deny.text
    assert await _permission_effective(o1, membre["userId"], PERMISSION_CIBLE) is False


async def test_be017_ca1_revocation_du_grant_allow_retire_le_droit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation révocation")
    await _ajouter_membre(o1, membre["userId"], [])
    url = _url_grants(membre["userId"])

    allow = await client.post(url, json={"permissionCode": PERMISSION_CIBLE, "effect": "allow"}, headers=_entetes(proprietaire, o1))
    assert allow.status_code == 201, allow.text
    assert await _permission_effective(o1, membre["userId"], PERMISSION_CIBLE) is True

    revoke = await client.delete(f"{url}/{allow.json()['id']}", headers=_entetes(proprietaire, o1))
    assert revoke.status_code == 204, revoke.text
    assert await _permission_effective(o1, membre["userId"], PERMISSION_CIBLE) is False


async def test_be017_ca2_refus_403_sans_permission_d_administration_et_aucun_grant_cree(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    sans_droit = await _inscrire_et_connecter(client, "Membre sans droit")
    membre = await _inscrire_et_connecter(client, "Membre cible")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA2")
    await _ajouter_membre(o1, sans_droit["userId"], [])
    await _ajouter_membre(o1, membre["userId"], [])

    res = await client.post(
        _url_grants(membre["userId"]),
        json={"permissionCode": PERMISSION_CIBLE, "effect": "deny"},
        headers=_entetes(sans_droit, o1),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"
    assert await _grants_de(o1, membre["userId"]) == 0


async def test_be017_ca2_acteur_sans_la_permission_accordee_ne_peut_pas_allow(client: AsyncClient):
    # Non-élévation : un gestionnaire de droits ne peut accorder (allow) une permission
    # qu'il ne possède pas lui-même. Le refus (deny) n'est pas soumis à cette règle.
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    gestionnaire = await _inscrire_et_connecter(client, "Gestionnaire de droits")
    membre = await _inscrire_et_connecter(client, "Membre cible")
    o1 = await _creer_organisation(client, proprietaire, "Organisation escalade")
    await _ajouter_membre(o1, gestionnaire["userId"], [PERMISSION_GESTION_DROITS])
    await _ajouter_membre(o1, membre["userId"], [])

    res = await client.post(
        _url_grants(membre["userId"]),
        json={"permissionCode": PERMISSION_CIBLE, "effect": "allow"},
        headers=_entetes(gestionnaire, o1),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "privilege_escalation_denied"
    assert await _grants_de(o1, membre["userId"]) == 0


async def test_be017_ca3_grant_vers_un_utilisateur_d_une_autre_organisation_refuse_en_404(client: AsyncClient):
    proprietaire_o1 = await _inscrire_et_connecter(client, "Propriétaire O1")
    proprietaire_o2 = await _inscrire_et_connecter(client, "Propriétaire O2")
    membre_o2 = await _inscrire_et_connecter(client, "Membre O2")
    o1 = await _creer_organisation(client, proprietaire_o1, "Organisation O1")
    o2 = await _creer_organisation(client, proprietaire_o2, "Organisation O2")
    await _ajouter_membre(o2, membre_o2["userId"], [])

    res = await client.post(
        _url_grants(membre_o2["userId"]),
        json={"permissionCode": PERMISSION_CIBLE, "effect": "deny"},
        headers=_entetes(proprietaire_o1, o1),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "user_not_found"
    assert await _grants_de(o2, membre_o2["userId"]) == 0
    assert await _grants_de(o1, membre_o2["userId"]) == 0


async def test_be017_ca3_revocation_d_un_grant_d_une_autre_organisation_refusee_en_404(client: AsyncClient):
    proprietaire_o1 = await _inscrire_et_connecter(client, "Propriétaire O1")
    proprietaire_o2 = await _inscrire_et_connecter(client, "Propriétaire O2")
    membre_o2 = await _inscrire_et_connecter(client, "Membre O2")
    o1 = await _creer_organisation(client, proprietaire_o1, "Organisation O1 révocation")
    o2 = await _creer_organisation(client, proprietaire_o2, "Organisation O2 révocation")
    await _ajouter_membre(o2, membre_o2["userId"], [])
    creation = await client.post(
        _url_grants(membre_o2["userId"]),
        json={"permissionCode": PERMISSION_CIBLE, "effect": "deny"},
        headers=_entetes(proprietaire_o2, o2),
    )
    assert creation.status_code == 201, creation.text

    res = await client.delete(f"{_url_grants(membre_o2['userId'])}/{creation.json()['id']}", headers=_entetes(proprietaire_o1, o1))
    assert res.status_code == 404, res.text
    assert await _grants_de(o2, membre_o2["userId"]) == 1


async def test_be017_droits_grant_d_un_autre_membre_ne_se_revoque_pas_par_ce_chemin(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre_a = await _inscrire_et_connecter(client, "Membre A")
    membre_b = await _inscrire_et_connecter(client, "Membre B")
    o1 = await _creer_organisation(client, proprietaire, "Organisation chemin")
    await _ajouter_membre(o1, membre_a["userId"], [])
    await _ajouter_membre(o1, membre_b["userId"], [])
    creation = await client.post(
        _url_grants(membre_a["userId"]),
        json={"permissionCode": PERMISSION_CIBLE, "effect": "allow"},
        headers=_entetes(proprietaire, o1),
    )
    assert creation.status_code == 201, creation.text

    res = await client.delete(f"{_url_grants(membre_b['userId'])}/{creation.json()['id']}", headers=_entetes(proprietaire, o1))
    assert res.status_code == 404, res.text
    assert await _permission_effective(o1, membre_a["userId"], PERMISSION_CIBLE) is True


async def test_be017_droits_permission_inconnue_refusee_en_404(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation permission inconnue")
    await _ajouter_membre(o1, membre["userId"], [])

    res = await client.post(
        _url_grants(membre["userId"]),
        json={"permissionCode": "inexistant.droit.xyz", "effect": "allow"},
        headers=_entetes(proprietaire, o1),
    )
    assert res.status_code == 404, res.text
    assert await _grants_de(o1, membre["userId"]) == 0


async def test_be017_ca4_creation_et_suppression_ecrivent_chacune_une_entree_d_audit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA4")
    await _ajouter_membre(o1, membre["userId"], [])
    url = _url_grants(membre["userId"])

    audit_creation_avant = await _nombre_audit(o1, ACTION_CREATION)
    creation = await client.post(url, json={"permissionCode": PERMISSION_CIBLE, "effect": "deny"}, headers=_entetes(proprietaire, o1))
    assert creation.status_code == 201, creation.text
    assert await _nombre_audit(o1, ACTION_CREATION) == audit_creation_avant + 1

    audit_revocation_avant = await _nombre_audit(o1, ACTION_REVOCATION)
    revocation = await client.delete(f"{url}/{creation.json()['id']}", headers=_entetes(proprietaire, o1))
    assert revocation.status_code == 204, revocation.text
    assert await _nombre_audit(o1, ACTION_REVOCATION) == audit_revocation_avant + 1
