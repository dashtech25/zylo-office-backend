"""BE-116 : moyens de paiement, ajout, remplacement et sélection (portail organisation).

Intention : prouver par des tests les critères d'acceptation de BE-116
(implementation-backend/tasks-portail-organisation.md, section BE-116) :
- CA-1 : une requête contenant PAN ou CVV retourne 400 et rien n'est stocké ;
- CA-2 : un ajout avec token seul retourne 201 ; la réponse n'expose pas le token ;
- CA-3 : sans `billing.payment_method.manage`, 403 ; organisation hors portée, 404 ;
- CA-4 : sans réauthentification (mot de passe courant), 403 ;
- CA-5 : chaque changement émet `PaymentMethodChanged` (double d'événements).

Routes testées :
- POST /api/v1/organizations/{organization_id}/billing/payment-methods
- POST /api/v1/organizations/{organization_id}/billing/payment-methods/{method}/select

Écarts (consignés dans le rapport) :
- la permission est `billing.payment_method.manage` (format `domaine.entite.action`, comme les
  autres codes billing), et non `billing:payment-method:manage` écrit dans la fiche ;
- la réauthentification est une preuve par mot de passe courant (champ `motDePasse`), faute de
  mécanisme de réauthentification dans develop ; le délai de PH-08 n'est pas repris ici.
"""

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing.models import PaymentMethodReference
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"
TOKEN_SECRET = "tok_be116_valeur_de_test_0042"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url_ajout(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/billing/payment-methods"


def _url_selection(organization_id: str, method_id: str) -> str:
    return f"{_url_ajout(organization_id)}/{method_id}/select"


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation sans rôle de gestion ; retourne son jeton d'accès."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be116-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-116",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_etrangere(client: AsyncClient) -> dict:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be116-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-116",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-116", "slug": f"be116-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()


async def _moyens_en_base(organization_id: uuid.UUID) -> list[PaymentMethodReference]:
    """Toutes les lignes de moyens de paiement d'une organisation, lues directement en base."""
    async with AsyncSessionLocal() as db:
        stmt = select(PaymentMethodReference).where(PaymentMethodReference.organizationId == organization_id)
        return list((await db.execute(stmt)).scalars().all())


async def _ajouter(client: AsyncClient, token: str, organization_id: str, token_reference: str = TOKEN_SECRET) -> dict:
    """Ajout d'un moyen de paiement par token avec réauthentification valide."""
    return await client.post(
        _url_ajout(organization_id),
        json={"tokenReference": token_reference, "motDePasse": MOT_DE_PASSE},
        headers=_entete(token, organization_id),
    )


async def test_ca1_pan_dans_le_corps_retourne_400_sans_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : un numéro de carte (PAN) dans la requête retourne 400 et rien n'est stocké."""
    org_id = organization["id"]

    reponse = await client.post(
        _url_ajout(org_id),
        json={"tokenReference": "4111 1111 1111 1111", "motDePasse": MOT_DE_PASSE},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 400, reponse.text
    assert reponse.json()["error"]["code"] == "card_data_refused"
    assert await _moyens_en_base(uuid.UUID(org_id)) == []


async def test_ca1_cvv_dans_le_corps_retourne_400_sans_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : un CVV ou un champ de carte dans la requête retourne 400 et rien n'est stocké."""
    org_id = organization["id"]

    reponse = await client.post(
        _url_ajout(org_id),
        json={"tokenReference": TOKEN_SECRET, "cvv": "123", "motDePasse": MOT_DE_PASSE},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 400, reponse.text
    assert reponse.json()["error"]["code"] == "card_data_refused"
    assert await _moyens_en_base(uuid.UUID(org_id)) == []


async def test_ca2_ajout_token_seul_retourne_201_sans_valeur_du_token(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un ajout avec token seul retourne 201 ; la valeur du token n'apparaît pas dans la réponse."""
    org_id = organization["id"]

    reponse = await _ajouter(client, registered_user["accessToken"], org_id)

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["selected"] is True
    assert UUID_RE.search(corps["id"]) is not None
    assert TOKEN_SECRET not in reponse.text
    lignes = await _moyens_en_base(uuid.UUID(org_id))
    assert [ligne.tokenReference for ligne in lignes] == [TOKEN_SECRET]


async def test_ca3_sans_permission_retourne_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (refus de droit) : un membre sans `billing.payment_method.manage` reçoit 403."""
    org_id = organization["id"]
    jeton = await _membre_sans_droit(client, uuid.UUID(org_id))

    reponse = await _ajouter(client, jeton, org_id)

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "permission_denied"
    assert await _moyens_en_base(uuid.UUID(org_id)) == []


async def test_ca3_organisation_hors_portee_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (isolation) : une organisation dont l'utilisateur n'est pas membre répond 404."""
    autre = await _organisation_etrangere(client)

    reponse = await _ajouter(client, registered_user["accessToken"], autre["id"])

    assert reponse.status_code == 404, reponse.text
    assert await _moyens_en_base(uuid.UUID(autre["id"])) == []


async def test_ca4_sans_reauthentification_retourne_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : sans réauthentification (mot de passe absent ou faux), la requête retourne 403."""
    org_id = organization["id"]
    entetes = _entete(registered_user["accessToken"], org_id)

    sans_mot_de_passe = await client.post(
        _url_ajout(org_id), json={"tokenReference": TOKEN_SECRET}, headers=entetes,
    )
    mauvais_mot_de_passe = await client.post(
        _url_ajout(org_id), json={"tokenReference": TOKEN_SECRET, "motDePasse": "Mauvais-Mot-2026!"}, headers=entetes,
    )

    assert sans_mot_de_passe.status_code == 403, sans_mot_de_passe.text
    assert mauvais_mot_de_passe.status_code == 403, mauvais_mot_de_passe.text
    assert await _moyens_en_base(uuid.UUID(org_id)) == []


async def test_ca5_chaque_changement_emet_payment_method_changed(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-5 : un ajout puis une sélection émettent chacun `PaymentMethodChanged` (double d'événements)."""
    from app.billing.payment_methods import service

    emis: list[dict] = []

    async def double_emission(db, donnees, *, emetteur_tenant):
        emis.append(donnees)

    monkeypatch.setattr(service, "emettre_evenement_facturation", double_emission)
    org_id = organization["id"]
    token = registered_user["accessToken"]

    ajout = await _ajouter(client, token, org_id)
    assert ajout.status_code == 201, ajout.text
    selection = await client.post(
        _url_selection(org_id, ajout.json()["id"]),
        json={"motDePasse": MOT_DE_PASSE},
        headers=_entete(token, org_id),
    )

    assert selection.status_code == 200, selection.text
    assert [evenement["eventType"] for evenement in emis] == ["PaymentMethodChanged", "PaymentMethodChanged"]
    assert [evenement["payload"]["action"] for evenement in emis] == ["added", "selected"]
    assert all(TOKEN_SECRET not in str(evenement) for evenement in emis)


async def test_remplacement_et_selection_gardent_une_seule_methode_selectionnee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Remplacement et sélection : une seule méthode est sélectionnée ; une méthode étrangère répond 404."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    premiere = (await _ajouter(client, token, org_id, "tok_be116_premier")).json()
    seconde = (await _ajouter(client, token, org_id, "tok_be116_second")).json()

    selection = await client.post(
        _url_selection(org_id, premiere["id"]), json={"motDePasse": MOT_DE_PASSE}, headers=_entete(token, org_id),
    )
    inconnue = await client.post(
        _url_selection(org_id, str(uuid.uuid4())), json={"motDePasse": MOT_DE_PASSE}, headers=_entete(token, org_id),
    )

    assert selection.status_code == 200, selection.text
    assert inconnue.status_code == 404, inconnue.text
    etats = {str(ligne.id): ligne.selected for ligne in await _moyens_en_base(uuid.UUID(org_id))}
    assert etats == {premiere["id"]: True, seconde["id"]: False}
