"""BE-033 : journal d'audit consultable par l'administrateur d'organisation.

Tests écrits d'après la définition `### BE-033` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Route cible : `GET /api/v1/organizations/current/audit-logs` (en-tête
`X-Organization-Id`, sélecteur validé par l'appartenance). Lecture seule, table
unique `audit_event` (BE-007), permission `audit.log.view` (code existant,
QE-SOC-06 encore ouvert).

Couverture :
- CA-1 (refus) : un membre sans permission reçoit 403 ;
- CA-2 (isolation) : la liste de O1 ne contient aucune entrée de O2 ;
- CA-3 : PUT, PATCH et DELETE renvoient 405 (lecture seule) ;
- CA-4 : les entrées retournées ne contiennent ni mot de passe ni jeton.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from sqlalchemy import select

from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User

ROUTE = "/api/v1/organizations/current/audit-logs"
MOT_DE_PASSE_SECRET = "Mdp-Secret-BE033-7788"
JETON_SECRET = "jeton-BE033-eyJhbGciOiJIUzI1NiJ9-secret"


async def _enregistrer_entree(organization_id: str, actor_user_id: str, summary: str, changes: dict | None = None) -> None:
    """Écrit une entrée d'audit réelle via le service (table audit_event)."""
    async with AsyncSessionLocal() as db:
        await record_audit_event(
            db,
            uuid.UUID(organization_id),
            uuid.UUID(actor_user_id),
            action="test.be033.entree",
            entity_type="TestBe033",
            entity_id=None,
            summary=summary,
            changes=changes,
        )
        await db.commit()


async def _id_utilisateur(email: str) -> str:
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(User).where(User.email == email))).scalar_one().id)


async def _ajouter_membre_sans_permission(email: str, organization_id: str) -> None:
    async with AsyncSessionLocal() as db:
        utilisateur = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()


async def test_be033_ca1_membre_sans_permission_recoit_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : un membre sans `audit.log.view` (aucun rôle, aucun grant) reçoit 403."""
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre Simple"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    await _ajouter_membre_sans_permission(email, organization["id"])

    headers = {"Authorization": f"Bearer {login.json()['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get(ROUTE, headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_be033_ca1_administrateur_d_organisation_recoit_la_liste(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Complément CA-1 : le propriétaire (porteur de `audit.log.view`) obtient 200
    et une page `data` / `meta`, avec les entrées de son organisation."""
    user_id = await _id_utilisateur(registered_user["email"])
    await _enregistrer_entree(organization["id"], user_id, "Entrée lisible BE-033")
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    res = await client.get(ROUTE, headers=headers)

    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["meta"]["total"] >= 1
    assert any(ligne["summary"] == "Entrée lisible BE-033" for ligne in corps["data"])


async def test_be033_ca2_isolation_aucune_entree_d_une_autre_organisation(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : la liste de O1 ne contient aucune entrée de O2, même si O2 a des
    entrées récentes et que le même utilisateur est membre des deux."""
    autre = await client.post(
        "/api/v1/organizations",
        json={"name": "Org Deux BE033", "slug": f"org-be033-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert autre.status_code == 201, autre.text
    org_deux = autre.json()["id"]
    user_id = await _id_utilisateur(registered_user["email"])
    await _enregistrer_entree(org_deux, user_id, "Entrée réservée à O2 BE033")
    await _enregistrer_entree(organization["id"], user_id, "Entrée de O1 BE033")

    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get(ROUTE, headers=headers)

    assert res.status_code == 200, res.text
    resumes = [ligne["summary"] for ligne in res.json()["data"]]
    assert "Entrée de O1 BE033" in resumes
    assert "Entrée réservée à O2 BE033" not in resumes


async def test_be033_ca3_ecriture_refusee_405(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : le journal est en lecture seule ; PUT, PATCH et DELETE renvoient 405."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    for methode in ("PUT", "PATCH", "DELETE"):
        res = await client.request(methode, ROUTE, headers=headers, json={"summary": "modifié"})
        assert res.status_code == 405, f"{methode} doit renvoyer 405, reçu {res.status_code}"


async def test_be033_ca4_aucun_mot_de_passe_ni_jeton_dans_les_entrees(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : même si l'appelant fournit des secrets dans `changes`, les entrées
    retournées ne contiennent ni le mot de passe, ni le jeton, ni leurs valeurs."""
    user_id = await _id_utilisateur(registered_user["email"])
    await _enregistrer_entree(
        organization["id"],
        user_id,
        "Changement de réglages BE033",
        changes={"motDePasse": MOT_DE_PASSE_SECRET, "accessToken": JETON_SECRET, "nom": "visible"},
    )
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    res = await client.get(ROUTE, headers=headers)

    assert res.status_code == 200, res.text
    brut = res.text
    assert MOT_DE_PASSE_SECRET not in brut
    assert JETON_SECRET not in brut
    entree = next(ligne for ligne in res.json()["data"] if ligne["summary"] == "Changement de réglages BE033")
    assert entree["changes"]["nom"] == "visible"
    assert entree["changes"]["motDePasse"] == "[masqué]"


async def test_be033_lecture_s_appuie_sur_la_table_audit_event(client: AsyncClient, registered_user: dict, organization: dict):
    """Pas de seconde table : l'entrée écrite dans `audit_event` est celle qui est lue."""
    user_id = await _id_utilisateur(registered_user["email"])
    await _enregistrer_entree(organization["id"], user_id, "Entrée table unique BE033")
    async with AsyncSessionLocal() as db:
        existe = await db.scalar(text(
            "SELECT count(*) FROM audit_event WHERE \"organizationId\" = :org AND summary = 'Entrée table unique BE033'"
        ).bindparams(org=uuid.UUID(organization["id"])))
    assert existe == 1
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    res = await client.get(ROUTE, headers=headers)

    assert any(ligne["summary"] == "Entrée table unique BE033" for ligne in res.json()["data"])
