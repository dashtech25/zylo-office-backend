"""BE-103 : demande et statut de vérification d'organisation.

Intention : prouver par des tests les critères d'acceptation de BE-103
(implementation-backend/tasks-portail-organisation.md, section BE-103) :
- CA-1 : POST par le propriétaire crée un cas en `verification_pending` et retourne 201 (test) ;
- CA-2 : GET par un membre sans droit retourne 403 ; GET sur une organisation hors portée
  retourne 404 (test de refus et d'isolation) ;
- CA-3 : la réponse d'un cas rejeté ne contient pas le motif interne (test) ;
- CA-4 : un POST contenant le statut `verified` est refusé et ne modifie rien (test : aucune
  décision par le client).

Routes testées :
- GET  /api/v1/organizations/{organization_id}/verification
- POST /api/v1/organizations/{organization_id}/verification

Dépendance : BE-102 (création d'organisation, `POST /api/v1/organizations` avec aucun Owner
attribué à la création) n'est pas encore fusionné dans develop. Les fixtures de `conftest.py`
utilisent la route de création existante ; le comportement « aucun Owner à la création » de
BE-102 n'est donc pas testé ici.

Écarts et hypothèses (la politique n'est pas définie, QE-POR-01 et QE-POR-07) :
- permission de dépôt et de lecture : NON DÉFINIE. Recommandation Owner ou Admin : seul le
  propriétaire est testé (le rôle Admin n'a pas de permission de vérification connue) ;
- codes HTTP de refus : 401, 403, 404 (spec) ; le code du POST refusé (CA-4) est accepté
  en 400 ou 422, la spec ne le fixe pas ;
- corps du POST : `{}` pour CA-1 (aucun champ n'est défini) ;
- table `verification_case` : colonnes `id`, `organizationId`, `statut`, `motifInterne`,
  `createdAt`, `updatedAt` (noms de colonnes supposés, la spec ne fixe que le statut) ;
- valeurs de statut : `verification_pending`, `verified`, `rejected` (spec).
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"
MOTIF_INTERNE = "MOTIF-INTERNE-BE103-7f3a9c"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/verification"


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation, sans aucun rôle. Retourne son jeton d'accès."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be103-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-103",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_etrangere(client: AsyncClient) -> dict:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be103-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-103",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-103", "slug": f"be103-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()


async def _cas_de_verification(organization_id: uuid.UUID) -> list[str]:
    """Statuts de tous les cas de vérification de l'organisation, lus directement en base."""
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            text('SELECT "statut" FROM verification_case WHERE "organizationId" = :org'),
            {"org": organization_id},
        )
        return [ligne[0] for ligne in resultat.all()]


async def _inserer_cas_rejete(organization_id: uuid.UUID) -> None:
    """Cas rejeté avec un motif interne, inséré directement (aucune route de décision n'est définie)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                'INSERT INTO verification_case (id, "organizationId", "statut", "motifInterne", "createdAt", "updatedAt") '
                "VALUES (:id, :org, 'rejected', :motif, now(), now())"
            ),
            {"id": uuid.uuid4(), "org": organization_id, "motif": MOTIF_INTERNE},
        )
        await db.commit()


async def test_be103_ca1_proprietaire_depose_une_demande_en_attente(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : POST par le propriétaire retourne 201 et crée un cas en `verification_pending`."""
    org_id = uuid.UUID(organization["id"])

    reponse = await client.post(
        _url(organization["id"]), json={}, headers=_entete(registered_user["accessToken"], organization["id"])
    )

    assert reponse.status_code == 201, reponse.text
    assert "verification_pending" in reponse.text, reponse.text
    assert await _cas_de_verification(org_id) == ["verification_pending"]


async def test_be103_ca2_membre_sans_droit_recoit_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : GET par un membre de l'organisation sans droit de lecture retourne 403."""
    jeton = await _membre_sans_droit(client, uuid.UUID(organization["id"]))

    reponse = await client.get(_url(organization["id"]), headers=_entete(jeton, organization["id"]))

    assert reponse.status_code == 403, reponse.text


async def test_be103_ca2_organisation_hors_portee_recoit_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : GET sur une organisation hors de la portée de l'utilisateur retourne 404.

    Précondition : le propriétaire lit sa propre organisation (200), pour que le 404 ne
    provienne pas d'une route absente.
    """
    propre = await client.get(
        _url(organization["id"]), headers=_entete(registered_user["accessToken"], organization["id"])
    )
    assert propre.status_code == 200, propre.text

    etrangere = await _organisation_etrangere(client)

    reponse = await client.get(
        _url(etrangere["id"]), headers=_entete(registered_user["accessToken"], etrangere["id"])
    )

    assert reponse.status_code == 404, reponse.text


async def test_be103_ca3_reponse_cas_rejete_sans_motif_interne(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : la réponse d'un cas rejeté ne contient ni le motif interne, ni aucune clé « motif »."""
    org_id = uuid.UUID(organization["id"])
    await _inserer_cas_rejete(org_id)

    reponse = await client.get(
        _url(organization["id"]), headers=_entete(registered_user["accessToken"], organization["id"])
    )

    assert reponse.status_code == 200, reponse.text
    assert "rejected" in reponse.text, reponse.text
    assert MOTIF_INTERNE not in reponse.text, reponse.text
    assert "motif" not in reponse.text.lower(), reponse.text


async def test_be103_ca4_statut_verified_envoye_par_le_client_est_refuse(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : un POST contenant le statut `verified` est refusé et ne crée ni ne modifie aucun cas."""
    org_id = uuid.UUID(organization["id"])

    reponse = await client.post(
        _url(organization["id"]),
        json={"statut": "verified"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code in (400, 422), reponse.text
    assert await _cas_de_verification(org_id) == [], "le client ne doit rien modifier"
