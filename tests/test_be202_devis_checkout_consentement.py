"""BE-202 : devis, checkout et consentement (routes `/api/v1/quotes`, `/api/v1/checkouts`, `/api/v1/consents`).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-donnees-api-contrats.md,
section BE-202) avant le code. Critères :
- CA-1 : un payeur sans rôle `billing.operate` reçoit 403 (refus) ;
- CA-2 : un essai sans consentement explicite est refusé 422 ;
- CA-3 : un devis d'un autre tenant renvoie 404 (isolation) ;
- CA-4 : un rejeu avec la même `Idempotency-Key` renvoie le même résultat sans second effet ;
- CA-5 : un devis sur une version de plan non publiée renvoie 422 ;
- CA-6 : un paiement ne crée aucun entitlement : la conséquence d'accès passe par BE-201.

Décisions de test (écarts consignés dans le rapport BE-202) :
- les tables `quote` et `checkout` existent déjà (BE-077, BE-081) : elles sont étendues, pas recréées ;
  `quote.status` porte l'état (`state` de la fiche), `quote.beneficiaryTenantId` le tenant ;
- la table `consent` (`consentId`, `payerId`, `kind`, `recordedAt`) est nouvelle ; `consent_record`
  (BE-076) n'est pas modifiée ;
- la permission `billing.operate` est nouvelle et accordée au propriétaire par défaut ;
- une version de plan est « publiée » quand son statut est `active` (BE-200) ; tout autre statut
  (ici `draft`) est « non publiée » ;
- `Idempotency-Key` est obligatoire sur les trois routes POST (socle BE-072).
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.billing import service
from app.billing.models import Checkout, PlanVersion, Quote
from app.billing.payers import creer_payeur
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User
from tests.conftest import _affecte_role_owner

MOT_DE_PASSE = "TestPassword123!"
URL_QUOTES = "/api/v1/quotes"
URL_CHECKOUTS = "/api/v1/checkouts"
URL_CONSENTS = "/api/v1/consents"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


# --- aides ------------------------------------------------------------------------


def _entete(token: str, organization_id: str, cle: str | None = None) -> dict[str, str]:
    """En-têtes d'une requête authentifiée sur un tenant, avec la clé d'idempotence si elle est donnée."""
    entete = {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}
    if cle is not None:
        entete["Idempotency-Key"] = cle
    return entete


async def _inscrire_et_connecter(client: AsyncClient, email: str) -> str:
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acheteur BE-202"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return login.json()["accessToken"]


async def _organisation_d_un_autre_tenant(client: AsyncClient) -> dict:
    """Second tenant, avec son propriétaire : sert au test d'isolation (CA-3)."""
    email = f"be202-autre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre tenant BE-202", "slug": f"be202-autre-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    organisation = res.json()
    await _affecte_role_owner(organisation["id"], email)
    return {"token": token, "organization": organisation}


async def _membre_sans_droit_de_facturation(client: AsyncClient, organization: dict) -> str:
    """Membre du tenant sans aucun rôle : il n'a pas `billing.operate` (CA-1)."""
    email = f"be202-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=membre.id))
        await db.commit()
    return token


async def _plan_publie() -> tuple[str, uuid.UUID]:
    """Offre du catalogue (module zylo_liquid) : renvoie son code et l'identifiant de sa version active."""
    async with AsyncSessionLocal() as db:
        code = f"be202-{uuid.uuid4().hex[:8]}"
        plan = await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-202", 1000, "XAF", 30)
        version = await db.scalar(select(PlanVersion).where(PlanVersion.planId == plan.id, PlanVersion.status == "active"))
        return code, version.id


async def _version_non_publiee(plan_code: str) -> uuid.UUID:
    """Ajoute à l'offre une version au statut `draft` : elle n'est pas publiée (CA-5)."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(db, "zylo_liquid", plan_code, "Plan BE-202", 1000, "XAF", 30)
        brouillon = PlanVersion(
            planId=plan.id, version=2, amountMinor=1000, currency="XAF", periodDays=30,
            entitlementCodes=[], status="draft", effectiveAt=datetime.now(timezone.utc),
        )
        db.add(brouillon)
        await db.commit()
        return brouillon.id


async def _payeur() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        payeur = await creer_payeur(db, "organisation", f"compte-be202-{uuid.uuid4().hex[:8]}")
        return payeur.id


async def _compter(sql: str, parametres: dict | None = None) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(sql), parametres or {})).scalar_one()


async def _creer_devis(client: AsyncClient, token: str, organization: dict, *, payeur_id: uuid.UUID,
                       plan_version_id: uuid.UUID, cle: str | None = None, essai: bool = False) -> dict:
    """Crée un devis par la route BE-202 et renvoie la réponse JSON (201 attendu)."""
    res = await client.post(
        URL_QUOTES,
        json={"planVersionId": str(plan_version_id), "payerId": str(payeur_id), "trial": essai},
        headers=_entete(token, organization["id"], cle or uuid.uuid4().hex),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _poser_consentement_essai(client: AsyncClient, token: str, organization: dict, payeur_id: uuid.UUID) -> None:
    res = await client.post(
        URL_CONSENTS,
        json={"payerId": str(payeur_id), "kind": "trial"},
        headers=_entete(token, organization["id"], uuid.uuid4().hex),
    )
    assert res.status_code == 201, res.text


# CA-1 : un payeur sans rôle `billing.operate` reçoit 403 sur les trois routes.


async def test_ca1_refus_403_sans_role_billing_operate(client: AsyncClient, registered_user, organization):
    plan_code, version_id = await _plan_publie()
    payeur_id = await _payeur()
    token_membre = await _membre_sans_droit_de_facturation(client, organization)
    entete_membre = _entete(token_membre, organization["id"], uuid.uuid4().hex)

    devis = await client.post(
        URL_QUOTES,
        json={"planVersionId": str(version_id), "payerId": str(payeur_id), "trial": False},
        headers=entete_membre,
    )
    assert devis.status_code == 403, devis.text

    consentement = await client.post(
        URL_CONSENTS,
        json={"payerId": str(payeur_id), "kind": "trial"},
        headers=entete_membre,
    )
    assert consentement.status_code == 403, consentement.text

    # Le propriétaire crée le devis ; le membre ne peut pas ouvrir de checkout dessus.
    devis_proprio = await _creer_devis(
        client, registered_user["accessToken"], organization, payeur_id=payeur_id, plan_version_id=version_id,
    )
    checkout = await client.post(
        URL_CHECKOUTS,
        json={"quoteId": devis_proprio["quoteId"]},
        headers=entete_membre,
    )
    assert checkout.status_code == 403, checkout.text
    assert await _compter("SELECT count(*) FROM checkout WHERE \"quoteId\" = :q", {"q": uuid.UUID(devis_proprio["quoteId"])}) == 0


# CA-2 : un essai sans consentement explicite est refusé 422 ; avec consentement, il passe.


async def test_ca2_essai_sans_consentement_explicite_refuse_422(client: AsyncClient, registered_user, organization):
    _, version_id = await _plan_publie()
    payeur_id = await _payeur()
    token = registered_user["accessToken"]
    devis = await _creer_devis(
        client, token, organization, payeur_id=payeur_id, plan_version_id=version_id, essai=True,
    )

    refuse = await client.post(
        URL_CHECKOUTS,
        json={"quoteId": devis["quoteId"]},
        headers=_entete(token, organization["id"], uuid.uuid4().hex),
    )
    assert refuse.status_code == 422, refuse.text
    assert refuse.json()["error"]["code"] == "TRIAL_CONSENT_REQUIRED"

    await _poser_consentement_essai(client, token, organization, payeur_id)
    accepte = await client.post(
        URL_CHECKOUTS,
        json={"quoteId": devis["quoteId"]},
        headers=_entete(token, organization["id"], uuid.uuid4().hex),
    )
    assert accepte.status_code == 201, accepte.text
    assert accepte.json()["state"] == "open"


# CA-3 : un devis d'un autre tenant renvoie 404, comme un devis inexistant.


async def test_ca3_devis_d_un_autre_tenant_404(client: AsyncClient, registered_user, organization):
    _, version_id = await _plan_publie()
    payeur_id = await _payeur()
    devis = await _creer_devis(
        client, registered_user["accessToken"], organization, payeur_id=payeur_id, plan_version_id=version_id,
    )
    autre = await _organisation_d_un_autre_tenant(client)

    res = await client.post(
        URL_CHECKOUTS,
        json={"quoteId": devis["quoteId"]},
        headers=_entete(autre["token"], autre["organization"]["id"], uuid.uuid4().hex),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "quote_not_found"
    assert await _compter("SELECT count(*) FROM checkout WHERE \"quoteId\" = :q", {"q": uuid.UUID(devis["quoteId"])}) == 0


# CA-4 : un rejeu avec la même `Idempotency-Key` renvoie le même résultat, sans second effet.


async def test_ca4_rejeu_meme_cle_meme_resultat_sans_second_effet(client: AsyncClient, registered_user, organization):
    _, version_id = await _plan_publie()
    payeur_id = await _payeur()
    token = registered_user["accessToken"]
    cle_devis = uuid.uuid4().hex
    premier_devis = await client.post(
        URL_QUOTES,
        json={"planVersionId": str(version_id), "payerId": str(payeur_id), "trial": False},
        headers=_entete(token, organization["id"], cle_devis),
    )
    rejeu_devis = await client.post(
        URL_QUOTES,
        json={"planVersionId": str(version_id), "payerId": str(payeur_id), "trial": False},
        headers=_entete(token, organization["id"], cle_devis),
    )
    assert premier_devis.status_code == 201, premier_devis.text
    assert rejeu_devis.status_code == 201, rejeu_devis.text
    assert rejeu_devis.json()["quoteId"] == premier_devis.json()["quoteId"]
    assert await _compter("SELECT count(*) FROM quote WHERE \"payerId\" = :p", {"p": payeur_id}) == 1

    cle_checkout = uuid.uuid4().hex
    premier = await client.post(
        URL_CHECKOUTS, json={"quoteId": premier_devis.json()["quoteId"]},
        headers=_entete(token, organization["id"], cle_checkout),
    )
    rejeu = await client.post(
        URL_CHECKOUTS, json={"quoteId": premier_devis.json()["quoteId"]},
        headers=_entete(token, organization["id"], cle_checkout),
    )
    assert premier.status_code == 201, premier.text
    assert rejeu.status_code == 201, rejeu.text
    assert rejeu.json()["checkoutId"] == premier.json()["checkoutId"]
    assert await _compter("SELECT count(*) FROM checkout WHERE \"quoteId\" = :q", {"q": uuid.UUID(premier_devis.json()["quoteId"])}) == 1


# CA-5 : un devis sur une version de plan non publiée renvoie 422 et ne crée aucun devis.


async def test_ca5_version_de_plan_non_publiee_422(client: AsyncClient, registered_user, organization):
    plan_code, _ = await _plan_publie()
    version_brouillon = await _version_non_publiee(plan_code)
    payeur_id = await _payeur()

    res = await client.post(
        URL_QUOTES,
        json={"planVersionId": str(version_brouillon), "payerId": str(payeur_id), "trial": False},
        headers=_entete(registered_user["accessToken"], organization["id"], uuid.uuid4().hex),
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "PLAN_VERSION_NOT_PUBLISHED"
    assert await _compter("SELECT count(*) FROM quote WHERE \"payerId\" = :p", {"p": payeur_id}) == 0


# CA-6 : un paiement (ici l'ouverture du checkout) ne crée aucun entitlement.


async def test_ca6_checkout_ne_cree_aucun_entitlement(client: AsyncClient, registered_user, organization):
    _, version_id = await _plan_publie()
    payeur_id = await _payeur()
    token = registered_user["accessToken"]
    devis = await _creer_devis(
        client, token, organization, payeur_id=payeur_id, plan_version_id=version_id,
    )
    entitlements_avant = await _compter("SELECT count(*) FROM subscription_entitlement")

    res = await client.post(
        URL_CHECKOUTS,
        json={"quoteId": devis["quoteId"]},
        headers=_entete(token, organization["id"], uuid.uuid4().hex),
    )
    assert res.status_code == 201, res.text
    assert res.json()["state"] == "open"
    assert await _compter("SELECT count(*) FROM subscription_entitlement") == entitlements_avant
