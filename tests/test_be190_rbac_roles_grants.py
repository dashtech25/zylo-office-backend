"""BE-190 : rôles, permissions, grants et autorisation serveur.

Tests écrits d'après la définition `### BE-190` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Routes testées (QE-API-01, listées dans CARTE-ROUTES.md) :
- GET  /api/v1/roles : rôles de l'organisation courante (en-tête X-Organization-Id).
- POST /api/v1/roles : déclaration d'un rôle avec ses codes de permission ; un code
  inconnu est refusé 422 (CA-3).
- POST /api/v1/roles/{role_id}/grants : attribue le rôle à un membre de
  l'organisation courante (corps : {"userId", "resourceType"?, "resourceId"?}).

Couverture des critères d'acceptation :
- CA-1 : une permission non accordée renvoie 403 (aucune écriture).
- CA-2 : un rôle d'un tenant ne s'applique pas à un autre tenant (404).
- CA-3 : une permission inconnue dans une déclaration est refusée 422.
- CA-4 : un rôle client ne peut pas accorder une permission plateforme (403).
- CA-5 : chaque attribution ou révocation écrit une entrée d'audit.
- CA-6 : un appel direct sans grant renvoie 403, même si l'interface masque le bouton.

Les rôles et appartenances de test sont posés directement en base, comme dans
test_be017_grants_membres.py.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_GESTION_ROLES = "rbac.role.manage"
PERMISSION_PLATEFORME = "platform.tenant.manage"
PERMISSION_LECTURE = "organization.members.read"
ACTION_ATTRIBUTION = "rbac.role.assign"
ACTION_REVOCATION = "rbac.role.unassign"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be190-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
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
        json={"name": nom, "slug": f"be190-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _permission(db, code: str) -> Permission:
    """Permission par code ; créée si elle n'existe pas encore dans la base de test."""
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-190")
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
            role = Role(organizationId=org, code=f"be190-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-190")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await _permission(db, code)
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _role_de_test(organisation_id: str, codes: list[str]) -> str:
    """Pose en base un rôle de l'organisation contenant ces permissions ; renvoie son identifiant."""
    org = uuid.UUID(organisation_id)
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org, code=f"be190-{uuid.uuid4().hex[:8]}", name="Rôle cible BE-190")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await _permission(db, code)
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()
        return str(role.id)


async def _attributions_de(organisation_id: str, utilisateur_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(UserRole.id)).where(
                    UserRole.organizationId == uuid.UUID(organisation_id),
                    UserRole.userId == uuid.UUID(utilisateur_id),
                )
            )
        ) or 0


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


async def test_be190_ca1_permission_absente_renvoie_403_sans_ecriture(client: AsyncClient):
    """CA-1 : un membre sans `rbac.role.manage` ne peut pas déclarer de rôle (403, rien créé)."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-1")
    org = await _creer_organisation(client, proprietaire, "Org CA-1")
    lecteur = await _inscrire_et_connecter(client, "Lecteur CA-1")
    await _ajouter_membre(org, lecteur["userId"], [PERMISSION_LECTURE])

    res = await client.post(
        "/api/v1/roles",
        json={"code": "lecture-seule", "name": "Lecture seule", "permissionCodes": [PERMISSION_LECTURE]},
        headers=_entetes(lecteur, org),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_be190_ca2_role_d_un_autre_tenant_renvoie_404(client: AsyncClient):
    """CA-2 : un rôle du tenant A, présenté sous le tenant B, renvoie 404 ; la lecture
    des rôles de B ne montre jamais les rôles de A."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-2")
    org_a = await _creer_organisation(client, proprietaire, "Org A CA-2")
    org_b = await _creer_organisation(client, proprietaire, "Org B CA-2")
    cible = await _inscrire_et_connecter(client, "Cible CA-2")
    await _ajouter_membre(org_b, cible["userId"], [])
    role_a = await _role_de_test(org_a, [PERMISSION_LECTURE])

    res = await client.post(
        f"/api/v1/roles/{role_a}/grants",
        json={"userId": cible["userId"]},
        headers=_entetes(proprietaire, org_b),
    )
    assert res.status_code == 404, res.text
    assert await _attributions_de(org_b, cible["userId"]) == 0

    liste = await client.get("/api/v1/roles", headers=_entetes(proprietaire, org_b))
    assert liste.status_code == 200, liste.text
    assert role_a not in [r["id"] for r in liste.json()]


async def test_be190_ca3_permission_inconnue_dans_une_declaration_renvoie_422(client: AsyncClient):
    """CA-3 : une permission absente du catalogue est refusée 422 à la déclaration du rôle."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-3")
    org = await _creer_organisation(client, proprietaire, "Org CA-3")

    res = await client.post(
        "/api/v1/roles",
        json={"code": "inconnu", "name": "Rôle inconnu", "permissionCodes": ["inexistant.module.action"]},
        headers=_entetes(proprietaire, org),
    )
    assert res.status_code == 422, res.text

    liste = await client.get("/api/v1/roles", headers=_entetes(proprietaire, org))
    assert "inconnu" not in [r["code"] for r in liste.json()]


async def test_be190_ca4_role_client_ne_peut_pas_accorder_une_permission_plateforme(client: AsyncClient):
    """CA-4 : un rôle client (même avec `rbac.role.manage`) ne peut pas attribuer un rôle
    qui contient une permission plateforme `platform.*` : 403, aucune attribution créée."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-4")
    org = await _creer_organisation(client, proprietaire, "Org CA-4")
    client_admin = await _inscrire_et_connecter(client, "Admin client CA-4")
    await _ajouter_membre(org, client_admin["userId"], [PERMISSION_GESTION_ROLES, PERMISSION_PLATEFORME])
    cible = await _inscrire_et_connecter(client, "Cible CA-4")
    await _ajouter_membre(org, cible["userId"], [])
    role_plateforme = await _role_de_test(org, [PERMISSION_PLATEFORME])

    res = await client.post(
        f"/api/v1/roles/{role_plateforme}/grants",
        json={"userId": cible["userId"]},
        headers=_entetes(client_admin, org),
    )
    assert res.status_code == 403, res.text
    assert await _attributions_de(org, cible["userId"]) == 0


async def test_be190_ca5_attribution_et_revocation_ecrivent_un_audit(client: AsyncClient):
    """CA-5 : l'attribution d'un rôle puis sa révocation écrivent chacune une entrée d'audit."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-5")
    org = await _creer_organisation(client, proprietaire, "Org CA-5")
    cible = await _inscrire_et_connecter(client, "Cible CA-5")
    await _ajouter_membre(org, cible["userId"], [])
    role = await _role_de_test(org, [PERMISSION_LECTURE])
    avant_attribution = await _nombre_audit(org, ACTION_ATTRIBUTION)

    res = await client.post(
        f"/api/v1/roles/{role}/grants",
        json={"userId": cible["userId"]},
        headers=_entetes(proprietaire, org),
    )
    assert res.status_code == 201, res.text
    assert await _nombre_audit(org, ACTION_ATTRIBUTION) == avant_attribution + 1

    attribution_id = res.json()["id"]
    avant_revocation = await _nombre_audit(org, ACTION_REVOCATION)
    revoque = await client.delete(
        f"/api/v1/rbac/organizations/{org}/user-roles/{attribution_id}",
        headers=_entetes(proprietaire, org),
    )
    assert revoque.status_code == 204, revoque.text
    assert await _nombre_audit(org, ACTION_REVOCATION) == avant_revocation + 1


async def test_be190_ca6_appel_direct_sans_grant_renvoie_403(client: AsyncClient):
    """CA-6 : un membre sans grant qui appelle directement la mutation (le bouton étant
    masqué côté interface) reçoit 403 ; aucune attribution n'est créée."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-6")
    org = await _creer_organisation(client, proprietaire, "Org CA-6")
    membre = await _inscrire_et_connecter(client, "Membre CA-6")
    await _ajouter_membre(org, membre["userId"], [])
    cible = await _inscrire_et_connecter(client, "Cible CA-6")
    await _ajouter_membre(org, cible["userId"], [])
    role = await _role_de_test(org, [PERMISSION_LECTURE])

    res = await client.post(
        f"/api/v1/roles/{role}/grants",
        json={"userId": cible["userId"]},
        headers=_entetes(membre, org),
    )
    assert res.status_code == 403, res.text
    assert await _attributions_de(org, cible["userId"]) == 0
