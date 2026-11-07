"""BE-110 : session de paiement, création et lecture d'état (portail organisation).

Intention : prouver les critères d'acceptation de BE-110
(implementation-backend/tasks-portail-organisation.md, section BE-110) :
- CA-1 : rejeu de `POST` avec la même clé d'idempotence retourne la même session, sans doublon ;
  même clé avec un corps différent retourne 409 ;
- CA-2 : `POST` sans consentement versionné retourne 400 et ne crée rien ;
- CA-3 : `GET` avec `?status=succeeded` dans l'URL retourne l'état durable, pas la query string ;
- CA-4 : `POST` sans `billing.checkout.purchase` retourne 403 ; `GET` sans `billing.subscription.read`
  retourne 403 ;
- CA-5 : session de l'organisation B demandée sous l'organisation A retourne 404 ;
- CA-6 : une publication de catalogue après création ne modifie pas l'offre figée de la session.

Routes testées :
- POST /api/v1/organizations/{organization_id}/checkout-sessions
- GET  /api/v1/organizations/{organization_id}/checkout-sessions/{session}

Écarts (consignés dans le rapport de lot) :
- la permission d'achat est `billing.checkout.purchase` (format `domaine.entite.action`), et non
  `billing:purchase` écrit dans la fiche ;
- la lecture exige `billing.subscription.read` (permission de lecture existante, BE-081), et non
  `billing:read` ;
- la clé d'idempotence est un en-tête `Idempotency-Key` ; absente, elle est refusée 422 par le socle
  (`require_idempotency_key`), comme les autres commandes du portail ;
- aucune migration : la session est portée par la table `checkout` (BE-081 / BE-202, QE-POR-29).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import Checkout, Quote
from app.billing.payers import creer_payeur
from app.billing.pricing.resolution import definir_regle_prix
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"
SCENARIO = "achat"
VERSION_TEXTE = "cgv-be110-v1"
EN_TETE_CLE = "Idempotency-Key"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url_sessions(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/checkout-sessions"


def _corps(plan_code: str, payeur_id: uuid.UUID, version: str = VERSION_TEXTE) -> dict:
    return {
        "planCode": plan_code,
        "scenario": SCENARIO,
        "payerId": str(payeur_id),
        "consentTextVersion": version,
    }


async def _creer_plan_et_payeur() -> tuple[str, uuid.UUID]:
    """Offre du catalogue (prix de référence) et compte payeur."""
    async with AsyncSessionLocal() as db:
        code = f"be110-{uuid.uuid4().hex[:8]}"
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-110", 1000, "XAF", 30)
        payeur = await creer_payeur(db, "organisation", f"compte-{uuid.uuid4().hex[:8]}")
        return code, payeur.id


async def _definir_prix(tenant_id: uuid.UUID, plan_code: str) -> None:
    async with AsyncSessionLocal() as db:
        await definir_regle_prix(
            db,
            organization_id=tenant_id,
            object_code=plan_code,
            scenario=SCENARIO,
            amount_minor=5000,
            currency="XAF",
            tax_rate_bps=1925,
        )


async def _preparer_offre(organization: dict) -> tuple[str, uuid.UUID]:
    """Plan et payeur prêts, avec un prix configuré pour le tenant. Renvoie (plan, payeur)."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    await _definir_prix(uuid.UUID(organization["id"]), plan_code)
    return plan_code, payeur_id


async def _poster_session(
    client: AsyncClient, token: str, organization_id: str, corps: dict, cle: str | None = None
):
    """POST de session avec une clé d'idempotence (fraîche par défaut)."""
    entetes = _entete(token, organization_id)
    entetes[EN_TETE_CLE] = cle or uuid.uuid4().hex
    return await client.post(_url_sessions(organization_id), json=corps, headers=entetes)


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation sans rôle de facturation ; renvoie son jeton d'accès."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be110-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-110",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_etrangere(client: AsyncClient) -> tuple[str, dict]:
    """Organisation d'un autre utilisateur. Renvoie (jeton du propriétaire, organisation)."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be110-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-110",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-110", "slug": f"be110-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return token, res.json()


async def _compter(organization_id: uuid.UUID) -> tuple[int, int]:
    """Nombre de devis et de checkouts du tenant, lus directement en base."""
    async with AsyncSessionLocal() as db:
        devis = await db.scalar(select(func.count()).select_from(Quote).where(Quote.beneficiaryTenantId == organization_id))
        checkouts = await db.scalar(
            select(func.count()).select_from(Checkout).join(Quote, Quote.id == Checkout.quoteId)
            .where(Quote.beneficiaryTenantId == organization_id)
        )
        return devis, checkouts


async def _publier_nouvelle_version(plan_code: str) -> None:
    """Publie une nouvelle version du plan avec un autre montant (modification du catalogue)."""
    async with AsyncSessionLocal() as db:
        await service.publish_plan_version(db, plan_code, 9900, "XAF", 365, ["be110.cap"])


async def test_ca1_rejeu_meme_cle_renvoie_meme_session_sans_doublon(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : deux `POST` avec la même clé renvoient la même session ; un seul checkout est créé."""
    org_id = organization["id"]
    plan_code, payeur_id = await _preparer_offre(organization)
    cle = uuid.uuid4().hex
    corps = _corps(plan_code, payeur_id)

    premier = await _poster_session(client, registered_user["accessToken"], org_id, corps, cle)
    rejeu = await _poster_session(client, registered_user["accessToken"], org_id, corps, cle)

    assert premier.status_code == 201, premier.text
    assert rejeu.status_code == 201, rejeu.text
    assert rejeu.json()["id"] == premier.json()["id"]
    assert await _compter(uuid.UUID(org_id)) == (1, 1)


async def test_ca1_meme_cle_avec_corps_different_retourne_409(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : même clé et corps différent retournent 409 ; rien de nouveau n'est écrit."""
    org_id = organization["id"]
    plan_code, payeur_id = await _preparer_offre(organization)
    cle = uuid.uuid4().hex

    premier = await _poster_session(client, registered_user["accessToken"], org_id, _corps(plan_code, payeur_id), cle)
    autre = await _poster_session(
        client, registered_user["accessToken"], org_id, _corps(plan_code, payeur_id, "cgv-be110-v2"), cle
    )

    assert premier.status_code == 201, premier.text
    assert autre.status_code == 409, autre.text
    assert await _compter(uuid.UUID(org_id)) == (1, 1)


async def test_ca2_post_sans_consentement_versionne_retourne_400_sans_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : sans `consentTextVersion` (ou vide), 400 `consent_required` ; aucun devis ni checkout."""
    org_id = organization["id"]
    plan_code, payeur_id = await _preparer_offre(organization)
    corps_sans = {"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}

    sans_champ = await _poster_session(client, registered_user["accessToken"], org_id, corps_sans)
    champ_vide = await _poster_session(client, registered_user["accessToken"], org_id, _corps(plan_code, payeur_id, ""))

    assert sans_champ.status_code == 400, sans_champ.text
    assert sans_champ.json()["error"]["code"] == "consent_required"
    assert champ_vide.status_code == 400, champ_vide.text
    assert await _compter(uuid.UUID(org_id)) == (0, 0)


async def test_ca3_get_ignore_la_query_string_et_lit_l_etat_durable(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : `?status=succeeded` dans l'URL ne change pas l'état ; la session reste `open`."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    plan_code, payeur_id = await _preparer_offre(organization)
    creee = await _poster_session(client, token, org_id, _corps(plan_code, payeur_id))
    session_id = creee.json()["id"]

    avec_query = await client.get(
        f"{_url_sessions(org_id)}/{session_id}?status=succeeded", headers=_entete(token, org_id)
    )
    sans_query = await client.get(f"{_url_sessions(org_id)}/{session_id}", headers=_entete(token, org_id))

    assert avec_query.status_code == 200, avec_query.text
    assert avec_query.json()["status"] == "open"
    assert sans_query.json()["status"] == "open"


async def test_ca4_post_refuse_sans_permission_d_achat(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : un membre sans `billing.checkout.purchase` reçoit 403 ; rien n'est écrit."""
    org_id = organization["id"]
    plan_code, payeur_id = await _preparer_offre(organization)
    token_membre = await _membre_sans_droit(client, uuid.UUID(org_id))

    reponse = await _poster_session(client, token_membre, org_id, _corps(plan_code, payeur_id))

    assert reponse.status_code == 403, reponse.text
    assert await _compter(uuid.UUID(org_id)) == (0, 0)


async def test_ca4_get_refuse_sans_permission_de_lecture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : un membre sans `billing.subscription.read` reçoit 403 sur la lecture d'une session."""
    org_id = organization["id"]
    plan_code, payeur_id = await _preparer_offre(organization)
    creee = await _poster_session(client, registered_user["accessToken"], org_id, _corps(plan_code, payeur_id))
    token_membre = await _membre_sans_droit(client, uuid.UUID(org_id))

    reponse = await client.get(
        f"{_url_sessions(org_id)}/{creee.json()['id']}", headers=_entete(token_membre, org_id)
    )

    assert reponse.status_code == 403, reponse.text


async def test_ca5_session_d_une_autre_organisation_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : une session de l'organisation B lue sous l'organisation A répond 404, comme un inconnu."""
    token_b, org_b = await _organisation_etrangere(client)
    plan_code, payeur_b = await _preparer_offre(org_b)
    session_b = await _poster_session(client, token_b, org_b["id"], _corps(plan_code, payeur_b))
    assert session_b.status_code == 201, session_b.text

    reponse = await client.get(
        f"{_url_sessions(organization['id'])}/{session_b.json()['id']}",
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 404, reponse.text


async def test_ca6_modification_du_catalogue_n_altere_pas_l_offre_figee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-6 : après une nouvelle version du plan, l'offre figée de la session reste identique."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    plan_code, payeur_id = await _preparer_offre(organization)
    creee = await _poster_session(client, token, org_id, _corps(plan_code, payeur_id))
    session_id = creee.json()["id"]
    offre_avant = creee.json()["offre"]

    await _publier_nouvelle_version(plan_code)

    relue = await client.get(f"{_url_sessions(org_id)}/{session_id}", headers=_entete(token, org_id))
    assert relue.status_code == 200, relue.text
    assert relue.json()["offre"] == offre_avant
    assert offre_avant["version"]["amountMinor"] == 1000
    assert offre_avant["version"]["periodDays"] == 30
