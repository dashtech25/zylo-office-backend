"""BE-014 : membres de l'organisation, liste et retrait.

Tests écrits d'après la définition `### BE-014` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Routes testées (recommandations de la définition, QE-SOC-04) :
- GET    /api/v1/organizations/current/members
- DELETE /api/v1/organizations/current/members/{userId}

Permissions (recommandations, QE-SOC-06) :
- lecture : `organization.members.read` ;
- retrait : `organization.members.remove`.

Couverture : CA-1 (liste limitée à l'organisation active, refus distinct
d'une liste vide), CA-2 (403 sans permission, appartenance conservée), CA-3
(isolation entre O1 et O2), CA-4 (retrait immédiat et entrée d'audit), CA-5
(rôle propriétaire protégé contre un non-propriétaire).

Les appartenances et rôles de test sont posés directement en base, comme dans
test_be004_appartenance.py : la tâche ne dépend pas de l'envoi d'invitation.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_LECTURE = "organization.members.read"
PERMISSION_RETRAIT = "organization.members.remove"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be014-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
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
        json={"name": nom, "slug": f"be014-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation. Si `permissions` est non vide,
    lui attribue un rôle transverse ne contenant que ces permissions."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be014-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-014")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                if permission is None:
                    permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-014")
                    db.add(permission)
                    await db.flush()
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _appartenance_existe(organisation_id: str, utilisateur_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        ligne = await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(utilisateur_id),
            )
        )
        return ligne is not None


async def _roles_de_l_utilisateur(organisation_id: str, utilisateur_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(UserRole.id)).where(
                    UserRole.organizationId == uuid.UUID(organisation_id),
                    UserRole.userId == uuid.UUID(utilisateur_id),
                )
            )
        ) or 0


async def _nombre_entrees_audit(organisation_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.organizationId == uuid.UUID(organisation_id)))
        ) or 0


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": utilisateur["authorization"], "X-Organization-Id": organisation_id}


async def test_be014_ca1_liste_ne_contient_que_les_membres_de_l_organisation_active(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire O1")
    autre_proprietaire = await _inscrire_et_connecter(client, "Propriétaire O2")
    membre = await _inscrire_et_connecter(client, "Membre O1")
    o1 = await _creer_organisation(client, proprietaire, "Organisation O1")
    o2 = await _creer_organisation(client, autre_proprietaire, "Organisation O2")
    await _ajouter_membre(o1, membre["userId"], [PERMISSION_LECTURE])

    liste = await client.get(f"/api/v1/organizations/current/members", headers=_entetes(proprietaire, o1))
    assert liste.status_code == 200, liste.text
    ids = {entree["userId"] for entree in liste.json()}
    assert ids == {proprietaire["userId"], membre["userId"]}
    assert autre_proprietaire["userId"] not in ids


async def test_be014_ca1_refus_distinct_de_la_liste_vide_et_de_l_erreur(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    sans_droit = await _inscrire_et_connecter(client, "Membre sans droit")
    intrus = await _inscrire_et_connecter(client, "Intrus")
    o1 = await _creer_organisation(client, proprietaire, "Organisation refus")
    await _ajouter_membre(o1, sans_droit["userId"], [])

    # Membre sans permission de lecture : refus 403, jamais une liste vide déguisée.
    refus_droit = await client.get("/api/v1/organizations/current/members", headers=_entetes(sans_droit, o1))
    assert refus_droit.status_code == 403, refus_droit.text

    # Non-membre : refus uniforme 404, sans donnée de l'organisation.
    refus_appartenance = await client.get("/api/v1/organizations/current/members", headers=_entetes(intrus, o1))
    assert refus_appartenance.status_code == 404, refus_appartenance.text
    assert proprietaire["userId"] not in refus_appartenance.text

    # Organisation sans autre membre que son propriétaire : liste de longueur 1, réponse 200.
    # Cet état ne se confond ni avec le refus (403/404) ni avec une erreur.
    seul = await _creer_organisation(client, proprietaire, "Organisation seule")
    liste = await client.get("/api/v1/organizations/current/members", headers=_entetes(proprietaire, seul))
    assert liste.status_code == 200, liste.text
    assert [entree["userId"] for entree in liste.json()] == [proprietaire["userId"]]


async def test_be014_ca2_refus_sans_permission_de_retrait_garde_l_appartenance(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    sans_droit = await _inscrire_et_connecter(client, "Membre sans retrait")
    cible = await _inscrire_et_connecter(client, "Membre visé")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA-2")
    await _ajouter_membre(o1, sans_droit["userId"], [PERMISSION_LECTURE])
    await _ajouter_membre(o1, cible["userId"], [])

    retrait = await client.delete(
        f"/api/v1/organizations/current/members/{cible['userId']}", headers=_entetes(sans_droit, o1)
    )
    assert retrait.status_code == 403, retrait.text
    assert await _appartenance_existe(o1, cible["userId"]) is True


async def test_be014_ca3_isolation_entre_organisations(client: AsyncClient):
    proprietaire_o1 = await _inscrire_et_connecter(client, "Propriétaire O1")
    proprietaire_o2 = await _inscrire_et_connecter(client, "Propriétaire O2")
    membre_o2 = await _inscrire_et_connecter(client, "Membre O2")
    o1 = await _creer_organisation(client, proprietaire_o1, "Organisation O1 isolée")
    o2 = await _creer_organisation(client, proprietaire_o2, "Organisation O2 isolée")
    await _ajouter_membre(o2, membre_o2["userId"], [])

    # Le propriétaire de O1 ne voit pas les membres de O2, même en désignant O2 par l'en-tête.
    liste_o2 = await client.get("/api/v1/organizations/current/members", headers=_entetes(proprietaire_o1, o2))
    assert liste_o2.status_code == 404, liste_o2.text
    assert membre_o2["userId"] not in liste_o2.text

    # Retrait d'un membre de O2 depuis le contexte de O1 : refusé, rien n'est retiré.
    retrait = await client.delete(
        f"/api/v1/organizations/current/members/{membre_o2['userId']}", headers=_entetes(proprietaire_o1, o1)
    )
    assert retrait.status_code == 404, retrait.text
    assert await _appartenance_existe(o2, membre_o2["userId"]) is True


async def test_be014_ca4_retrait_revoque_l_acces_et_journalise(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    retire = await _inscrire_et_connecter(client, "Membre retiré")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA-4")
    await _ajouter_membre(o1, retire["userId"], [PERMISSION_LECTURE])
    assert await _roles_de_l_utilisateur(o1, retire["userId"]) == 1  # rôle de test attribué

    audit_avant = await _nombre_entrees_audit(o1)
    retrait = await client.delete(
        f"/api/v1/organizations/current/members/{retire['userId']}", headers=_entetes(proprietaire, o1)
    )
    assert retrait.status_code in (200, 204), retrait.text

    # Appartenance et rôles de l'organisation supprimés, entrée d'audit ajoutée.
    assert await _appartenance_existe(o1, retire["userId"]) is False
    assert await _roles_de_l_utilisateur(o1, retire["userId"]) == 0
    assert await _nombre_entrees_audit(o1) == audit_avant + 1

    # Accès révoqué dès la requête suivante.
    apres = await client.get("/api/v1/organizations/current/members", headers=_entetes(retire, o1))
    assert apres.status_code == 404, apres.text


async def test_be014_ca5_non_proprietaire_ne_retire_pas_le_proprietaire(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    gestionnaire = await _inscrire_et_connecter(client, "Gestionnaire des membres")
    o1 = await _creer_organisation(client, proprietaire, "Organisation CA-5")
    await _ajouter_membre(o1, gestionnaire["userId"], [PERMISSION_RETRAIT, PERMISSION_LECTURE])

    # Le gestionnaire a la permission de retrait, mais pas le rôle propriétaire : refus 403.
    refus = await client.delete(
        f"/api/v1/organizations/current/members/{proprietaire['userId']}", headers=_entetes(gestionnaire, o1)
    )
    assert refus.status_code == 403, refus.text
    assert await _appartenance_existe(o1, proprietaire["userId"]) is True

    # Témoin positif : le même gestionnaire peut retirer un membre ordinaire (le 403 vise le rôle).
    ordinaire = await _inscrire_et_connecter(client, "Membre ordinaire")
    await _ajouter_membre(o1, ordinaire["userId"], [])
    retrait = await client.delete(
        f"/api/v1/organizations/current/members/{ordinaire['userId']}", headers=_entetes(gestionnaire, o1)
    )
    assert retrait.status_code in (200, 204), retrait.text
    assert await _appartenance_existe(o1, ordinaire["userId"]) is False
