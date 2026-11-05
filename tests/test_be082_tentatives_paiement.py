"""BE-082 : tentatives de paiement et soumission (`POST /billing/checkouts/{checkoutId}/payment-attempts`).

Intention : prouver les critères d'acceptation de BE-082
(implementation-backend/tasks-abonnements-facturation.md, section BE-082) :
- CA-1 : la tentative est enregistrée (`created` puis `submitted`) AVANT l'appel au fournisseur :
  le fournisseur fictif observe la ligne `submitted` au moment de son appel ;
- CA-2 : un délai dépassé sans réponse place la tentative en `unknown`, jamais `failed` ;
- CA-3 : sans permission d'acheteur (ACTF-04, `billing.subscription.manage`) : `FORBIDDEN`,
  le fournisseur n'est pas appelé ;
- CA-4 : une tentative visant un checkout du tenant A n'est pas soumise depuis le scope B :
  réponse identique à un checkout inexistant (404 `checkout_not_found`) ;
- CA-5 : aucune donnée de carte n'est persistée (schéma et payload).

Hors CA, mais contrat de la définition : `PAYMENT_DECLINED` (402, QE-FAC-02),
`PROVIDER_UNAVAILABLE` (503), rejeu d'une même clé d'idempotence (BE-072), refus de soumettre
un checkout qui n'est pas `open` (`INVALID_TRANSITION`).

Le fournisseur est remplacé par un adaptateur fictif (interface `PaymentProvider`, BE-028) via
`app.dependency_overrides`. Aucun appel réseau n'est fait.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.billing import service
from app.billing.models import ConsentRecord
from app.billing.payers import creer_payeur
from app.billing.pricing.resolution import definir_regle_prix
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User

SCENARIO = "achat"
MOT_DE_PASSE = "TestPassword123!"
VERSION_TEXTE_CONSENTEMENT = "cgv-2026-11"
CLE_IDEMPOTENCE = "be082-cle-idempotence-0001"
NUMERO_CARTE_TEST = "4242424242424242"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


class FournisseurFictif:
    """Adaptateur fictif de `PaymentProvider` (BE-028) : enregistre les appels et simule une issue.

    `issue` vaut `accepte`, `refuse` (débit refusé) ou `delai` (aucune réponse). Au moment de
    l'appel, il relit la ligne de la tentative en base : c'est la preuve du CA-1.
    """

    provider = "fictif"
    mode = "test"

    def __init__(self, issue: str):
        self.issue = issue
        self.appels: list[tuple[int, str, str]] = []
        self.statuts_au_debit: list[str | None] = []

    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        self.appels.append((amount_cents, currency, reference))
        self.statuts_au_debit.append(await _statut_tentative(reference))
        if self.issue == "delai":
            raise asyncio.TimeoutError()
        return self.issue == "accepte"

    async def create_checkout(self, amount_minor: int, currency: str, reference: str):
        raise NotImplementedError


@pytest.fixture
def poser_fournisseur():
    """Remplace le fournisseur de la route par un adaptateur fictif, retiré après le test."""
    from app.billing.payment_attempts.router import obtenir_fournisseur
    from app.main import app

    def _poser(issue: str) -> FournisseurFictif:
        fournisseur = FournisseurFictif(issue)
        app.dependency_overrides[obtenir_fournisseur] = lambda: fournisseur
        return fournisseur

    yield _poser
    app.dependency_overrides.pop(obtenir_fournisseur, None)


# --- aides ------------------------------------------------------------------------


def _url_tentatives(checkout_id: str) -> str:
    return f"/api/v1/billing/checkouts/{checkout_id}/payment-attempts"


def _entete(token: str, organization_id: str, cle: str = CLE_IDEMPOTENCE) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id, "Idempotency-Key": cle}


async def _inscrire_et_connecter(client, email: str) -> str:
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(client, organization_id: str) -> str:
    """Membre du tenant sans rôle : aucune permission d'acheteur."""
    email = f"be082-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=membre.id))
        await db.commit()
    return token


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _checkout_ouvert(client, registered_user, organization) -> tuple[str, str]:
    """Chaîne minimale jusqu'à un checkout `open` (BE-077, BE-076, BE-081). Renvoie (checkout, devis).

    Le montant vient du snapshot de prix du devis (BE-078) : aucune valeur de prix n'est codée ici.
    """
    async with AsyncSessionLocal() as db:
        code = f"be082-{uuid.uuid4().hex[:8]}"
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-082", 1000, "XAF", 30)
        payeur = await creer_payeur(db, "organisation", f"compte-{uuid.uuid4().hex[:8]}")
        await definir_regle_prix(
            db, organization_id=uuid.UUID(organization["id"]), object_code=code, scenario=SCENARIO,
            amount_minor=5000, currency="XAF", tax_rate_bps=1925,
        )
        payeur_id = payeur.id
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    devis = await client.post(
        "/api/v1/billing/quotes", json={"planCode": code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers,
    )
    assert devis.status_code == 201, devis.text
    devis_id = devis.json()["id"]
    accepte = await client.post(f"/api/v1/billing/quotes/{devis_id}/accept", json={}, headers=headers)
    assert accepte.status_code == 200, accepte.text
    async with AsyncSessionLocal() as db:
        db.add(ConsentRecord(
            personId=await _id_utilisateur(registered_user["email"]), accountId=payeur_id,
            consentTextVersion=VERSION_TEXTE_CONSENTEMENT, scope="payeur",
        ))
        await db.commit()
    checkout = await client.post(
        "/api/v1/billing/checkouts", json={"quoteId": devis_id}, headers=headers,
    )
    assert checkout.status_code == 201, checkout.text
    return checkout.json()["id"], devis_id


async def _statut_tentative(attempt_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text('SELECT status FROM "paymentAttempt" WHERE id = :id'), {"id": uuid.UUID(attempt_id)})


async def _tentatives_du_checkout(checkout_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(
            text('SELECT * FROM "paymentAttempt" WHERE "checkoutId" = :c'), {"c": uuid.UUID(checkout_id)},
        )).mappings().all()
        return [dict(ligne) for ligne in lignes]


async def _statut_checkout(checkout_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT status FROM checkout WHERE id = :id"), {"id": uuid.UUID(checkout_id)})


async def _tenant_b(client, registered_user) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be082-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


# --- CA-1 : enregistrement avant l'appel fournisseur -----------------------------


async def test_ca1_tentative_enregistree_avant_appel_fournisseur(client, registered_user, organization, poser_fournisseur):
    """CA-1 : la ligne est `submitted` au moment de l'appel ; après réponse acceptée elle est `pending`."""
    checkout_id, devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["status"] == "pending"
    assert corps["checkoutId"] == checkout_id
    assert len(fournisseur.appels) == 1
    montant, devise, reference = fournisseur.appels[0]
    assert reference == corps["id"]
    assert fournisseur.statuts_au_debit == ["submitted"]
    assert montant == (await _tentatives_du_checkout(checkout_id))[0]["amountMinor"]
    assert devise == "XAF"
    ligne = (await _tentatives_du_checkout(checkout_id))[0]
    assert ligne["submittedAt"] is not None
    assert await _statut_checkout(checkout_id) == "pending"


async def test_ca1_refus_de_debit_donne_paiement_refuse_et_checkout_reouvert(client, registered_user, organization, poser_fournisseur):
    """Débit refusé : 402 `PAYMENT_DECLINED`, tentative `failed`, checkout de nouveau `open` pour une nouvelle tentative."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    poser_fournisseur("refuse")
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert res.status_code == 402, res.text
    assert res.json()["error"]["code"] == "PAYMENT_DECLINED"
    assert (await _tentatives_du_checkout(checkout_id))[0]["status"] == "failed"
    assert await _statut_checkout(checkout_id) == "open"


async def test_fournisseur_indisponible_donne_503_sans_transaction(client, registered_user, organization):
    """Adaptateur sandbox non configuré (stub BE-028) : 503 `PROVIDER_UNAVAILABLE`, tentative `failed`, aucun débit."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert res.status_code == 503, res.text
    assert res.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    ligne = (await _tentatives_du_checkout(checkout_id))[0]
    assert ligne["status"] == "failed"
    assert ligne["providerReference"] is None


# --- CA-2 : délai dépassé ---------------------------------------------------------


async def test_ca2_delai_depasse_place_la_tentative_en_unknown_jamais_failed(client, registered_user, organization, poser_fournisseur):
    """CA-2 : pas de réponse à temps -> 202 et statut `unknown` ; le checkout reste `pending`."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("delai")
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert res.status_code == 202, res.text
    assert res.json()["status"] == "unknown"
    assert len(fournisseur.appels) == 1
    ligne = (await _tentatives_du_checkout(checkout_id))[0]
    assert ligne["status"] == "unknown"
    assert ligne["status"] != "failed"
    assert await _statut_checkout(checkout_id) == "pending"


# --- CA-3 : permission ------------------------------------------------------------


async def test_ca3_sans_permission_d_acheteur_forbidden_sans_appel_fournisseur(client, registered_user, organization, poser_fournisseur):
    """CA-3 : membre sans droit d'acheteur -> 403 `FORBIDDEN` ; le fournisseur n'est pas appelé ; rien n'est écrit."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    token_membre = await _ajouter_membre_sans_droit(client, organization["id"])
    headers = _entete(token_membre, organization["id"])

    res = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert fournisseur.appels == []
    assert await _tentatives_du_checkout(checkout_id) == []
    assert await _statut_checkout(checkout_id) == "open"


# --- CA-4 : isolation tenant ------------------------------------------------------


async def test_ca4_tentative_d_un_checkout_du_tenant_a_depuis_le_tenant_b_traitee_comme_inexistant(
    client, registered_user, organization, poser_fournisseur,
):
    """CA-4 : soumission depuis le scope B d'un checkout du tenant A -> 404 `checkout_not_found`, comme un inconnu."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    tenant_b = await _tenant_b(client, registered_user)
    headers_b = _entete(registered_user["accessToken"], tenant_b)

    res_existant = await client.post(_url_tentatives(checkout_id), json={}, headers=headers_b)
    res_inconnu = await client.post(_url_tentatives(str(uuid.uuid4())), json={}, headers=headers_b)

    assert res_existant.status_code == 404, res_existant.text
    assert res_inconnu.status_code == 404
    assert res_existant.json()["error"]["code"] == res_inconnu.json()["error"]["code"] == "checkout_not_found"
    assert fournisseur.appels == []
    assert await _tentatives_du_checkout(checkout_id) == []


# --- CA-5 : aucune donnée de carte ------------------------------------------------


async def test_ca5_aucun_numero_de_carte_en_base_ni_dans_la_reponse(client, registered_user, organization, poser_fournisseur):
    """CA-5 : un payload contenant une carte n'est ni persisté, ni transmis, ni renvoyé."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    headers = _entete(registered_user["accessToken"], organization["id"])
    payload = {"cardNumber": NUMERO_CARTE_TEST, "cvv": "123", "expiryMonth": 12, "expiryYear": 2030}

    res = await client.post(_url_tentatives(checkout_id), json=payload, headers=headers)

    assert res.status_code in (201, 202), res.text
    assert NUMERO_CARTE_TEST not in res.text
    assert all(NUMERO_CARTE_TEST not in str(valeur) for appel in fournisseur.appels for valeur in appel)
    for ligne in await _tentatives_du_checkout(checkout_id):
        assert all(NUMERO_CARTE_TEST not in str(valeur) for valeur in ligne.values())


async def test_ca5_schema_de_la_table_sans_colonne_de_carte():
    """CA-5 : aucune colonne de `paymentAttempt` ne porte un numéro de carte, un CVV ou une date d'expiration."""
    async with AsyncSessionLocal() as db:
        colonnes = (await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'paymentAttempt'"
        ))).scalars().all()
    interdits = ("card", "pan", "cvv", "cvc", "expir", "iban")
    assert colonnes
    assert not [c for c in colonnes if any(motif in c.lower() for motif in interdits)]


# --- contrat de la table et de la machine d'état ----------------------------------


async def test_table_paymentattempt_porte_les_colonnes_de_la_definition():
    """La table existante `paymentAttempt` est réutilisée (pas de doublon) et porte les colonnes de BE-082."""
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(text(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'paymentAttempt'"
        ))).all()
    colonnes = {nom: nullable for nom, nullable in lignes}
    for requise in ("id", "checkoutId", "status", "version", "submittedAt", "providerReference"):
        assert requise in colonnes, requise
    assert colonnes["invoiceId"] == "YES"
    assert colonnes["checkoutId"] == "YES"


async def test_rejeu_de_la_meme_cle_renvoie_la_meme_tentative_sans_rappeler_le_fournisseur(
    client, registered_user, organization, poser_fournisseur,
):
    """BE-072 : même clé, même commande -> même tentative, un seul appel fournisseur."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    headers = _entete(registered_user["accessToken"], organization["id"])

    premier = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)
    rejeu = await client.post(_url_tentatives(checkout_id), json={}, headers=headers)

    assert premier.status_code == 201, premier.text
    assert rejeu.json()["id"] == premier.json()["id"]
    assert len(fournisseur.appels) == 1
    assert len(await _tentatives_du_checkout(checkout_id)) == 1


async def test_soumission_refusee_si_le_checkout_n_est_pas_open(client, registered_user, organization, poser_fournisseur):
    """Un checkout `pending` ne peut pas être soumis une seconde fois : 409 `INVALID_TRANSITION`, pas d'appel."""
    checkout_id, _devis_id = await _checkout_ouvert(client, registered_user, organization)
    fournisseur = poser_fournisseur("accepte")
    premier = await client.post(
        _url_tentatives(checkout_id), json={}, headers=_entete(registered_user["accessToken"], organization["id"]),
    )
    assert premier.status_code == 201, premier.text

    second = await client.post(
        _url_tentatives(checkout_id), json={},
        headers=_entete(registered_user["accessToken"], organization["id"], cle="be082-cle-idempotence-0002"),
    )

    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "INVALID_TRANSITION"
    assert len(fournisseur.appels) == 1
