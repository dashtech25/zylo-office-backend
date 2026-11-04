"""BE-011 : réglages d'organisation minimum.

Tests écrits d'après la définition `### BE-011` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Routes (non définies dans la définition, QE-SOC-04 ; chemins de la définition) :
- GET delta : GET /api/v1/organizations/current/settings
- PUT       : PUT /api/v1/organizations/current/settings

Permissions :
- lecture : tout membre actif (aucune permission particulière) ;
- écriture : `organization.settings.update` (recommandation QE-SOC-06).

Couverture : CA-1 (sauvegarde puis relecture), CA-2 (403 sans permission
d'écriture, valeur inchangée), CA-3 (isolation : 404 hors organisation),
CA-4 (entrée d'audit à chaque modification réussie), CA-5 (nom vide : 422
avec `field_errors` au format BE-001).

Les appartenances et rôles de test sont posés directement en base, comme dans
test_be014_membres.py.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
URL_REGLAGES = "/api/v1/organizations/current/settings"
PERMISSION_ECRITURE_REGLAGES = "organization.settings.update"
PERMISSION_LECTURE_MEMBRES = "organization.members.read"
ACTION_AUDIT_MODIFICATION = "identity.organization.update"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie son en-tête d'authentification et son identifiant."""
    email = f"be011-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
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
        json={"name": nom, "slug": f"be011-{uuid.uuid4().hex[:10]}"},
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
            role = Role(organizationId=org, code=f"be011-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-011")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                if permission is None:
                    permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-011")
                    db.add(permission)
                    await db.flush()
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _nom_en_base(organisation_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(Organization, uuid.UUID(organisation_id))).name


async def _nombre_audits_modification(organisation_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.organizationId == uuid.UUID(organisation_id),
                    AuditEvent.action == ACTION_AUDIT_MODIFICATION,
                )
            )
        ) or 0


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": utilisateur["authorization"], "X-Organization-Id": organisation_id}


async def test_be011_ca1_sauvegarde_puis_relecture_du_nom_persiste(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-011")
    org = await _creer_organisation(client, proprietaire, "Nom initial BE-011")

    sauvegarde = await client.put(URL_REGLAGES, json={"name": "Nom sauvegardé BE-011"}, headers=_entetes(proprietaire, org))
    assert sauvegarde.status_code == 200, sauvegarde.text

    # Relecture après rechargement : nouvelle requête, la valeur vient de la base.
    relecture = await client.get(URL_REGLAGES, headers=_entetes(proprietaire, org))
    assert relecture.status_code == 200, relecture.text
    corps = relecture.json()
    assert corps["name"] == "Nom sauvegardé BE-011"
    assert corps["id"] == org
    assert corps["slug"]
    assert corps["status"]
    assert await _nom_en_base(org) == "Nom sauvegardé BE-011"


async def test_be011_ca1_lecture_ouverte_a_tout_membre_sans_permission_particuliere(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire lecture")
    membre = await _inscrire_et_connecter(client, "Membre sans droit BE-011")
    org = await _creer_organisation(client, proprietaire, "Org lecture BE-011")
    await _ajouter_membre(org, membre["userId"], [])

    lecture = await client.get(URL_REGLAGES, headers=_entetes(membre, org))

    assert lecture.status_code == 200, lecture.text
    assert lecture.json()["name"] == "Org lecture BE-011"


async def test_be011_ca2_membre_sans_permission_d_ecriture_recoit_403_et_rien_ne_change(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA2")
    membre = await _inscrire_et_connecter(client, "Membre lecture seule BE-011")
    org = await _creer_organisation(client, proprietaire, "Org CA2 BE-011")
    # Le membre a la lecture des membres, mais pas l'écriture des réglages.
    await _ajouter_membre(org, membre["userId"], [PERMISSION_LECTURE_MEMBRES])

    refus = await client.put(URL_REGLAGES, json={"name": "Tentative sans droit BE-011"}, headers=_entetes(membre, org))

    assert refus.status_code == 403, refus.text
    assert await _nom_en_base(org) == "Org CA2 BE-011"


async def test_be011_ca3_administrateur_de_o1_ne_modifie_jamais_o2(client: AsyncClient):
    admin_o1 = await _inscrire_et_connecter(client, "Admin O1 BE-011")
    admin_o2 = await _inscrire_et_connecter(client, "Admin O2 BE-011")
    o1 = await _creer_organisation(client, admin_o1, "Organisation O1 BE-011")
    o2 = await _creer_organisation(client, admin_o2, "Organisation O2 BE-011")

    # Session de l'administrateur de O1, sélecteur forcé sur O2 : hors appartenance, 404.
    tentative = await client.put(URL_REGLAGES, json={"name": "Piratage BE-011"}, headers=_entetes(admin_o1, o2))

    assert tentative.status_code == 404, tentative.text
    assert await _nom_en_base(o2) == "Organisation O2 BE-011"
    assert await _nom_en_base(o1) == "Organisation O1 BE-011"


async def test_be011_ca4_modification_reussie_cree_une_entree_d_audit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA4")
    org = await _creer_organisation(client, proprietaire, "Org CA4 BE-011")
    avant = await _nombre_audits_modification(org)

    res = await client.put(URL_REGLAGES, json={"name": "Org CA4 modifiée BE-011"}, headers=_entetes(proprietaire, org))

    assert res.status_code == 200, res.text
    assert await _nombre_audits_modification(org) == avant + 1


async def test_be011_ca5_nom_vide_refuse_en_422_avec_field_errors(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA5")
    org = await _creer_organisation(client, proprietaire, "Org CA5 BE-011")

    res = await client.put(URL_REGLAGES, json={"name": ""}, headers=_entetes(proprietaire, org))

    assert res.status_code == 422, res.text
    erreur = res.json()["error"]
    assert erreur["code"] == "validation_error"
    assert any("name" in chemin for chemin in erreur["field_errors"])
    assert res.json()["request_id"] == res.headers["X-Request-Id"]
    assert await _nom_en_base(org) == "Org CA5 BE-011"


async def test_be011_sans_session_la_route_de_reglages_est_refusee(client: AsyncClient, organization: dict):
    res = await client.put(URL_REGLAGES, json={"name": "Anonyme BE-011"}, headers={"X-Organization-Id": organization["id"]})

    assert res.status_code == 401, res.text
