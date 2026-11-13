"""BE-015 : affectation des rôles aux membres de l'organisation courante.

Tests écrits d'après la définition `### BE-015` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Route testée (non définie par la tâche, QE-SOC-04 ; forme retenue ici) :
- PUT /api/v1/organizations/current/members/{userId}/roles
  corps : {"roleIds": [...]} ; l'ensemble des rôles transverses de la cible
  dans l'organisation courante devient exactement `roleIds`.

Permission (non définie, QE-SOC-06 ; reprise de l'existante) :
- `rbac.role.manage` (ROLE_MANAGE), déjà accordée au propriétaire.

Couverture : CA-1 (affectation valide persistée, revalidée côté serveur),
CA-2 (403 sans permission, aucune affectation modifiée), CA-3 (non-propriétaire
ne peut ni attribuer ni retirer le rôle propriétaire), CA-4 (rôle d'une autre
organisation : 404, rien n'est écrit dans O1), CA-5 (chaque affectation crée une
entrée d'audit).

Les rôles et appartenances de test sont posés directement en base, comme dans
test_be014_membres.py.
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
PERMISSION_LECTURE = "organization.members.read"
PERMISSION_RETRAIT = "organization.members.remove"
ACTION_ATTRIBUTION = "rbac.role.assign"
ACTION_RETRAIT = "rbac.role.unassign"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be015-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
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
        json={"name": nom, "slug": f"be015-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation ; si `permissions` est non vide, lui
    attribue un rôle transverse ne contenant que ces permissions."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be015-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-015")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                if permission is None:
                    permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-015")
                    db.add(permission)
                    await db.flush()
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _creer_role(organisation_id: str, permissions: list[str]) -> str:
    """Crée un rôle transverse de l'organisation, contenant `permissions`, et renvoie son identifiant."""
    org = uuid.UUID(organisation_id)
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org, code=f"be015-{uuid.uuid4().hex[:8]}", name="Rôle affecté BE-015")
        db.add(role)
        await db.flush()
        for code in permissions:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-015")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()
        return str(role.id)


async def _role_proprietaire(organisation_id: str) -> str:
    async with AsyncSessionLocal() as db:
        role_id = await db.scalar(
            select(Role.id).where(Role.organizationId == uuid.UUID(organisation_id), Role.code == "owner")
        )
        return str(role_id)


async def _roles_transverses(organisation_id: str, utilisateur_id: str) -> set[str]:
    """Identifiants des rôles transverses (sans portée) de l'utilisateur dans l'organisation."""
    async with AsyncSessionLocal() as db:
        lignes = await db.scalars(
            select(UserRole.roleId).where(
                UserRole.organizationId == uuid.UUID(organisation_id),
                UserRole.userId == uuid.UUID(utilisateur_id),
                UserRole.resourceType.is_(None),
            )
        )
        return {str(role_id) for role_id in lignes}


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


async def test_be015_ca1_affectation_valide_persistee_et_revalidee_cote_serveur(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA1")
    await _ajouter_membre(o1, membre["userId"], [])
    role_lecture = await _creer_role(o1, [PERMISSION_LECTURE])

    res = await client.put(
        f"/api/v1/organizations/current/members/{membre['userId']}/roles",
        json={"roleIds": [role_lecture]},
        headers=_entetes(proprietaire, o1),
    )
    assert res.status_code == 200, res.text
    assert role_lecture in {entree["id"] for entree in res.json()["roles"]}
    assert await _roles_transverses(o1, membre["userId"]) == {role_lecture}


async def test_be015_ca1_refus_si_le_role_contient_une_permission_que_l_acteur_n_a_pas(client: AsyncClient):
    # Revalidation serveur : un acteur qui ne possède pas une permission ne peut pas
    # l'accorder par un rôle, même avec `rbac.role.manage`.
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    gestionnaire = await _inscrire_et_connecter(client, "Gestionnaire de rôles")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation escalade")
    await _ajouter_membre(o1, gestionnaire["userId"], [PERMISSION_GESTION_ROLES])
    await _ajouter_membre(o1, membre["userId"], [])
    role_retrait = await _creer_role(o1, [PERMISSION_RETRAIT])

    res = await client.put(
        f"/api/v1/organizations/current/members/{membre['userId']}/roles",
        json={"roleIds": [role_retrait]},
        headers=_entetes(gestionnaire, o1),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "privilege_escalation_denied"
    assert await _roles_transverses(o1, membre["userId"]) == set()


async def test_be015_ca2_refus_403_sans_permission_et_affectations_inchangees(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    sans_droit = await _inscrire_et_connecter(client, "Membre sans droit")
    membre = await _inscrire_et_connecter(client, "Membre affecté")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA2")
    await _ajouter_membre(o1, sans_droit["userId"], [])
    await _ajouter_membre(o1, membre["userId"], [])
    role_existant = await _creer_role(o1, [PERMISSION_LECTURE])
    role_nouveau = await _creer_role(o1, [PERMISSION_LECTURE])
    async with AsyncSessionLocal() as db:
        db.add(UserRole(userId=uuid.UUID(membre["userId"]), organizationId=uuid.UUID(o1), roleId=uuid.UUID(role_existant)))
        await db.commit()

    res = await client.put(
        f"/api/v1/organizations/current/members/{membre['userId']}/roles",
        json={"roleIds": [role_nouveau]},
        headers=_entetes(sans_droit, o1),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"
    assert await _roles_transverses(o1, membre["userId"]) == {role_existant}


async def test_be015_ca3_non_proprietaire_ne_peut_ni_attribuer_ni_retirer_le_role_proprietaire(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    gestionnaire = await _inscrire_et_connecter(client, "Gestionnaire de rôles")
    cible = await _inscrire_et_connecter(client, "Cible")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA3")
    await _ajouter_membre(o1, gestionnaire["userId"], [PERMISSION_GESTION_ROLES])
    await _ajouter_membre(o1, cible["userId"], [])
    role_proprietaire = await _role_proprietaire(o1)
    url = f"/api/v1/organizations/current/members/{cible['userId']}/roles"

    attribution = await client.put(url, json={"roleIds": [role_proprietaire]}, headers=_entetes(gestionnaire, o1))
    assert attribution.status_code == 403, attribution.text
    assert attribution.json()["error"]["code"] == "owner_assignment_forbidden"
    assert await _roles_transverses(o1, cible["userId"]) == set()

    # Le propriétaire actuel est retiré par le gestionnaire : refus, il reste propriétaire.
    proprietaire_cible_avant = await _roles_transverses(o1, proprietaire["userId"])
    retrait = await client.put(
        f"/api/v1/organizations/current/members/{proprietaire['userId']}/roles",
        json={"roleIds": []},
        headers=_entetes(gestionnaire, o1),
    )
    assert retrait.status_code == 403, retrait.text
    assert retrait.json()["error"]["code"] == "owner_assignment_forbidden"
    assert await _roles_transverses(o1, proprietaire["userId"]) == proprietaire_cible_avant


async def test_be015_ca3_dernier_proprietaire_ne_peut_pas_etre_retire(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire unique")
    o1 = await _creer_organisation(client, proprietaire, "Organisation dernier propriétaire")

    res = await client.put(
        f"/api/v1/organizations/current/members/{proprietaire['userId']}/roles",
        json={"roleIds": []},
        headers=_entetes(proprietaire, o1),
    )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "last_owner"
    assert await _role_proprietaire(o1) in await _roles_transverses(o1, proprietaire["userId"])


async def test_be015_ca4_role_d_une_autre_organisation_refuse_en_404(client: AsyncClient):
    proprietaire_o1 = await _inscrire_et_connecter(client, "Propriétaire O1")
    proprietaire_o2 = await _inscrire_et_connecter(client, "Propriétaire O2")
    membre = await _inscrire_et_connecter(client, "Membre O1")
    o1 = await _creer_organisation(client, proprietaire_o1, "Organisation O1")
    o2 = await _creer_organisation(client, proprietaire_o2, "Organisation O2")
    await _ajouter_membre(o1, membre["userId"], [])
    role_o2 = await _creer_role(o2, [PERMISSION_LECTURE])

    res = await client.put(
        f"/api/v1/organizations/current/members/{membre['userId']}/roles",
        json={"roleIds": [role_o2]},
        headers=_entetes(proprietaire_o1, o1),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "role_not_found"
    assert await _roles_transverses(o1, membre["userId"]) == set()


async def test_be015_ca4_cible_absente_de_l_organisation_refusee_en_404(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    etranger = await _inscrire_et_connecter(client, "Étranger")
    o1 = await _creer_organisation(client, proprietaire, "Organisation cible absente")
    role_lecture = await _creer_role(o1, [PERMISSION_LECTURE])

    res = await client.put(
        f"/api/v1/organizations/current/members/{etranger['userId']}/roles",
        json={"roleIds": [role_lecture]},
        headers=_entetes(proprietaire, o1),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "user_not_found"
    assert await _roles_transverses(o1, etranger["userId"]) == set()


async def test_be015_ca5_chaque_affectation_et_chaque_retrait_ecrit_une_entree_d_audit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    membre = await _inscrire_et_connecter(client, "Membre")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA5")
    await _ajouter_membre(o1, membre["userId"], [])
    role_a = await _creer_role(o1, [PERMISSION_LECTURE])
    role_b = await _creer_role(o1, [PERMISSION_LECTURE])
    url = f"/api/v1/organizations/current/members/{membre['userId']}/roles"

    audit_attribution_avant = await _nombre_audit(o1, ACTION_ATTRIBUTION)
    res = await client.put(url, json={"roleIds": [role_a, role_b]}, headers=_entetes(proprietaire, o1))
    assert res.status_code == 200, res.text
    assert await _nombre_audit(o1, ACTION_ATTRIBUTION) == audit_attribution_avant + 2

    audit_retrait_avant = await _nombre_audit(o1, ACTION_RETRAIT)
    res = await client.put(url, json={"roleIds": [role_a]}, headers=_entetes(proprietaire, o1))
    assert res.status_code == 200, res.text
    assert await _roles_transverses(o1, membre["userId"]) == {role_a}
    assert await _nombre_audit(o1, ACTION_RETRAIT) == audit_retrait_avant + 1
