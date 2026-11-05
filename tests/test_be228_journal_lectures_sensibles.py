"""BE-228 : journal des lectures sensibles et journal opérateur.

Tests écrits d'après la définition `### BE-228` (implementation-backend/
tasks-exploitation-architecture.md), avant le code de l'extension.

Couverture :
- CA-1 : chaque consultation d'une organisation par un opérateur produit une entrée
  portant le tenant ciblé ;
- CA-2 : non-régression : les tests BE-030 existants restent verts (exécutés à part,
  ce fichier ne les duplique pas) ;
- CA-3 : un opérateur non habilité reçoit 403 et la tentative est journalisée (refus) ;
- CA-4 : la liste du journal opérateur ne montre qu'un tenant si le filtre le demande ;
- motif : une lecture peut porter un motif court, conservé dans l'entrée ; sans motif,
  aucune clé `motif` n'apparaît (pas de charge utile).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal, engine
from app.operator.audit import lister_lectures_operateur, record_operator_read


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le pool est vidé après chaque test : les tests changent de boucle asyncio."""
    yield
    await engine.dispose()


async def _moi(client: AsyncClient, registered_user: dict, monkeypatch, autorise: bool = True) -> tuple[dict, str]:
    """En-têtes d'authentification et identifiant de l'utilisateur de test.

    Si `autorise` est vrai, l'utilisateur est ajouté à la liste d'exploitation ; sinon
    la liste ne contient qu'un autre identifiant."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    user_id = (await client.get("/api/v1/auth/me", headers=headers)).json()["id"]
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", user_id if autorise else str(uuid.uuid4()))
    return headers, user_id


async def _entrees_par_requete(request_id: str) -> list[AuditEvent]:
    """Entrées opérateur de `audit_event` portant ce request ID."""
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(
            select(AuditEvent).where(AuditEvent.request_id == request_id, AuditEvent.action.like("operator.%"))
        )).all())


async def _creer_organisation(client: AsyncClient, headers: dict) -> dict:
    """Crée une organisation supplémentaire pour le même utilisateur."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"be228-{uuid.uuid4().hex[:8]}"},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_be228_ca1_consultation_organisation_produit_une_entree_avec_tenant_cible(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, user_id = await _moi(client, registered_user, monkeypatch)

    reponse = await client.get(
        f"/api/v1/admin/organizations/{organization['id']}",
        headers={**headers, "X-Request-Id": "be228-ca1-organisation"},
    )
    assert reponse.status_code == 200

    (entree,) = await _entrees_par_requete("be228-ca1-organisation")
    assert str(entree.actorUserId) == user_id
    assert entree.action == "operator.organization.read"
    assert entree.scopeResourceType == "organization"
    assert str(entree.scopeResourceId) == organization["id"]
    assert entree.result == "success"


async def test_be228_ca3_operateur_non_habilite_recoit_403_et_refus_journalise(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, user_id = await _moi(client, registered_user, monkeypatch, autorise=False)

    reponse = await client.get(
        f"/api/v1/admin/organizations/{organization['id']}",
        headers={**headers, "X-Request-Id": "be228-ca3-refus"},
    )
    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "operator_access_denied"

    entrees = await _entrees_par_requete("be228-ca3-refus")
    assert len(entrees) == 1
    assert entrees[0].result == "refused"
    assert str(entrees[0].actorUserId) == user_id


async def test_be228_ca4_liste_filtree_par_tenant_ne_montre_pas_les_autres_tenants(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, _ = await _moi(client, registered_user, monkeypatch)
    autre = await _creer_organisation(client, headers)
    for cible in (organization["id"], autre["id"]):
        await client.get(f"/api/v1/admin/organizations/{cible}", headers=headers)

    async with AsyncSessionLocal() as db:
        toutes = await lister_lectures_operateur(db)
        filtre_a = await lister_lectures_operateur(db, organization_id=uuid.UUID(organization["id"]))
        filtre_b = await lister_lectures_operateur(db, organization_id=uuid.UUID(autre["id"]))

    ids_a = {str(e.scopeResourceId) for e in filtre_a}
    ids_b = {str(e.scopeResourceId) for e in filtre_b}
    assert ids_a == {organization["id"]}
    assert ids_b == {autre["id"]}
    assert {organization["id"], autre["id"]} <= {str(e.scopeResourceId) for e in toutes}


async def test_be228_motif_conserve_quand_fourni_et_absent_sinon(
    client: AsyncClient, registered_user: dict,
):
    acteur = uuid.UUID((await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )).json()["id"])
    async with AsyncSessionLocal() as db:
        avec = await record_operator_read(
            db, actor_user_id=acteur, scope="platform", action="console.access",
            target_type="operator_console", outcome="success", request_id="be228-motif-avec",
            motif="verification_support",
        )
        sans = await record_operator_read(
            db, actor_user_id=acteur, scope="platform", action="console.access",
            target_type="operator_console", outcome="success", request_id="be228-motif-sans",
        )
    assert avec.changes == {"outcome": "success", "motif": "verification_support"}
    assert sans.changes == {"outcome": "success"}
