"""BE-118 : demande de support client (portail organisation).

Intention : prouver par des tests les critères d'acceptation de BE-118
(implementation-backend/tasks-portail-organisation.md, section BE-118) :
- CA-1 : création valide 201, statut `open`, événement `SupportRequestCreated` dans l'outbox ;
- CA-2 : un contexte contenant un mot de passe ou un token est refusé en 400, rien n'est stocké ;
- CA-3 : sans `support.request.create`, 403 ;
- CA-4 : organisation B sous l'organisation A, 404 (isolation tenant) ;
- CA-5 : `createdBy` est toujours l'identité authentifiée, quelle que soit la valeur du corps.

Route testée :
- POST /api/v1/organizations/{organization_id}/support-requests

Écarts (consignés dans le rapport) :
- la permission est `support.request.create` (format `domaine.entite.action`, comme
  `billing.payment_method.manage`), et non `support:create` écrit dans la fiche ;
- la permission est accordée au propriétaire par défaut (OWNER_DEFAULT_PERMISSIONS) ; aucun
  autre rôle ne la reçoit dans cette tâche.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.evenements.models import OutboxEvenement
from app.identity.models import OrganizationUser
from app.support.models import SupportRequest

MOT_DE_PASSE = "TestPassword123!"
TYPE_EVENEMENT = "SupportRequestCreated"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/support-requests"


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> dict:
    """Utilisateur rattaché à l'organisation sans rôle de support ; retourne son identifiant et son jeton."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be118-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-118",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return {"id": membre.json()["id"], "accessToken": login.json()["accessToken"]}


async def _organisation_etrangere(client: AsyncClient) -> dict:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be118-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-118",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-118", "slug": f"be118-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()


async def _demandes_en_base(organization_id: uuid.UUID) -> list[SupportRequest]:
    """Toutes les demandes de support d'une organisation, lues directement en base."""
    async with AsyncSessionLocal() as db:
        stmt = select(SupportRequest).where(SupportRequest.organizationId == organization_id)
        return list((await db.execute(stmt)).scalars().all())


async def _evenements_en_base(organization_id: uuid.UUID) -> list[OutboxEvenement]:
    """Événements `SupportRequestCreated` écrits dans l'outbox pour une organisation."""
    async with AsyncSessionLocal() as db:
        stmt = select(OutboxEvenement).where(
            OutboxEvenement.eventType == TYPE_EVENEMENT, OutboxEvenement.tenantId == organization_id
        )
        return list((await db.execute(stmt)).scalars().all())


async def test_ca1_demande_valide_retourne_201_statut_open_et_evenement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : une demande valide retourne 201 avec le statut `open` et émet `SupportRequestCreated`."""
    org_id = organization["id"]

    reponse = await client.post(
        _url(org_id),
        json={"contexte": {"page": "/org/x/help", "message": "Impossible d'ouvrir un export."}},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["statut"] == "open"
    demandes = await _demandes_en_base(uuid.UUID(org_id))
    assert len(demandes) == 1 and demandes[0].statut == "open"
    evenements = await _evenements_en_base(uuid.UUID(org_id))
    assert len(evenements) == 1
    assert evenements[0].payload["payload"]["supportRequestId"] == str(demandes[0].id)


async def test_ca2_contexte_avec_mot_de_passe_ou_token_retourne_400_sans_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un mot de passe ou un token dans le contexte retourne 400 ; rien n'est stocké ni émis."""
    org_id = organization["id"]
    entete = _entete(registered_user["accessToken"], org_id)

    reponse_mot_de_passe = await client.post(
        _url(org_id), json={"contexte": {"motDePasse": "secret-du-client"}}, headers=entete,
    )
    reponse_token = await client.post(
        _url(org_id), json={"contexte": {"diagnostic": {"api_token": "tok_be118_valeur"}}}, headers=entete,
    )

    assert reponse_mot_de_passe.status_code == 400, reponse_mot_de_passe.text
    assert reponse_token.status_code == 400, reponse_token.text
    assert "secret-du-client" not in reponse_mot_de_passe.text
    assert await _demandes_en_base(uuid.UUID(org_id)) == []
    assert await _evenements_en_base(uuid.UUID(org_id)) == []


async def test_ca3_sans_permission_support_retourne_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : un membre sans `support.request.create` reçoit 403 et rien n'est créé."""
    org_id = organization["id"]
    membre = await _membre_sans_droit(client, uuid.UUID(org_id))

    reponse = await client.post(
        _url(org_id), json={"contexte": {"message": "Aide"}},
        headers=_entete(membre["accessToken"], org_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert await _demandes_en_base(uuid.UUID(org_id)) == []


async def test_ca4_organisation_b_sous_organisation_a_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : demander un support pour l'organisation B avec un jeton de l'organisation A répond 404."""
    autre_org = await _organisation_etrangere(client)

    reponse = await client.post(
        _url(autre_org["id"]), json={"contexte": {"message": "Aide"}},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 404, reponse.text
    assert await _demandes_en_base(uuid.UUID(autre_org["id"])) == []


async def test_ca5_created_by_est_toujours_l_identite_authentifiee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : un `createdBy` fourni dans le corps est ignoré ; l'auteur stocké est l'utilisateur authentifié."""
    org_id = organization["id"]
    usurpe = str(uuid.uuid4())

    reponse = await client.post(
        _url(org_id),
        json={"contexte": {"message": "Aide"}, "createdBy": usurpe},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 201, reponse.text
    demandes = await _demandes_en_base(uuid.UUID(org_id))
    assert len(demandes) == 1
    assert str(demandes[0].createdBy) == reponse.json()["createdBy"]
    assert str(demandes[0].createdBy) != usurpe
    assert reponse.json()["createdBy"] == (await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"}
    )).json()["id"]
