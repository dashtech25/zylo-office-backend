"""BE-081 : achat par checkout (`POST /billing/checkouts`, `GET /billing/checkouts/{checkoutId}`).

Intention : prouver les critères d'acceptation de BE-081
(implementation-backend/tasks-abonnements-facturation.md, section BE-081) :
- CA-1 : un checkout n'est créé que depuis un devis `accepted` avec consentement requis
  enregistré ; sinon `CONSENT_REQUIRED` (devis accepté sans consentement) ou
  `INVALID_TRANSITION` / `QUOTE_EXPIRED` (devis non accepté, devis expiré) ; rien n'est écrit ;
- CA-2 : le client ne peut pas passer un checkout à `completed` ; le checkout reste `open`
  (la confirmation viendra de BE-083 / BE-084) ;
- CA-3 : `POST` sans permission d'acheteur (ACTF-04, `billing.subscription.manage`) renvoie
  `FORBIDDEN` ; rien n'est écrit ;
- CA-4 : `GET` d'un checkout du tenant A depuis le tenant B répond comme un checkout
  inexistant (404 `checkout_not_found`), à l'identique.

Hors CA : lecture par le tenant propriétaire, refus de lecture sans permission de lecture,
structure exacte de la table `checkout` et contrainte sur les statuts.

Décisions consignées : la permission de lecture est `billing.subscription.read` (approximation
d'ACTF-04/ACTF-05, voir BE-077 et QE-FAC-03). Le devis porte le tenant : la table `checkout`
n'a pas de colonne tenant, le périmètre passe par `quote.beneficiaryTenantId` (colonnes
exactes NON DÉFINIES, QE-FAC-04). La durée d'expiration du devis n'est pas définie (QE-FAC-21) :
le test pose `expiresAt` directement en base.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.billing import service
from app.billing.models import ConsentRecord
from app.billing.payers import creer_payeur
from app.billing.pricing.resolution import definir_regle_prix
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User

SCENARIO = "achat"
MOT_DE_PASSE = "TestPassword123!"
VERSION_TEXTE_CONSENTEMENT = "cgv-2026-11"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


# --- aides ------------------------------------------------------------------------


def _url_devis(quote_id: str | None = None, action: str | None = None) -> str:
    base = "/api/v1/billing/quotes"
    if quote_id is None:
        return base
    return f"{base}/{quote_id}" if action is None else f"{base}/{quote_id}/{action}"


def _url_checkout(checkout_id: str | None = None) -> str:
    base = "/api/v1/billing/checkouts"
    return base if checkout_id is None else f"{base}/{checkout_id}"


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _inscrire_et_connecter(client, email: str) -> str:
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(client, organization_id: str) -> str:
    """Membre du tenant sans rôle : aucune permission d'acheteur ni de lecture."""
    email = f"be081-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=membre.id))
        await db.commit()
    return token


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(User.id).where(User.email == email)))


async def _creer_plan_et_payeur() -> tuple[str, uuid.UUID]:
    """Offre du catalogue (zylo_liquid, prix de référence) et compte payeur."""
    async with AsyncSessionLocal() as db:
        code = f"be081-{uuid.uuid4().hex[:8]}"
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-081", 1000, "XAF", 30)
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


async def _creer_devis_priced(client, registered_user, organization) -> tuple[str, uuid.UUID]:
    """Devis `priced` créé par le propriétaire du tenant (BE-077). Renvoie (devis, payeur)."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    await _definir_prix(uuid.UUID(organization["id"]), plan_code)
    headers = _entete(registered_user["accessToken"], organization["id"])
    res = await client.post(
        _url_devis(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["id"], payeur_id


async def _creer_devis_accepte(client, registered_user, organization) -> tuple[str, uuid.UUID]:
    devis_id, payeur_id = await _creer_devis_priced(client, registered_user, organization)
    headers = _entete(registered_user["accessToken"], organization["id"])
    res = await client.post(_url_devis(devis_id, "accept"), json={}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "accepted"
    return devis_id, payeur_id


async def _consentir(payeur_id: uuid.UUID, personne_id: uuid.UUID) -> None:
    """Consentement requis enregistré pour le compte payeur (BE-076, ligne `consent_record`)."""
    async with AsyncSessionLocal() as db:
        db.add(ConsentRecord(
            personId=personne_id,
            accountId=payeur_id,
            consentTextVersion=VERSION_TEXTE_CONSENTEMENT,
            scope="payeur",
        ))
        await db.commit()


async def _poser_expiration_passee(quote_id: str) -> None:
    """La durée d'expiration n'est pas définie (QE-FAC-21) : on fixe une date passée en base."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text('UPDATE quote SET "expiresAt" = :passe WHERE id = :id'),
            {"passe": datetime.now(timezone.utc) - timedelta(days=1), "id": uuid.UUID(quote_id)},
        )
        await db.commit()


async def _lire_checkout(checkout_id: str) -> dict | None:
    """Lecture brute de la ligne `checkout` (le test ne dépend pas du modèle ORM)."""
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(text("SELECT * FROM checkout WHERE id = :id"), {"id": uuid.UUID(checkout_id)})).mappings().first()
        return dict(ligne) if ligne is not None else None


async def _compter_checkouts(quote_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.execute(text("SELECT id FROM checkout WHERE \"quoteId\" = :q"), {"q": uuid.UUID(quote_id)})).all())


# --- CA-1 : devis accepté et consentement requis -----------------------------------


async def test_ca1_checkout_refuse_sans_consentement_enregistre(client, registered_user, organization):
    """CA-1 : devis `accepted` mais aucun consentement -> CONSENT_REQUIRED (422) ; rien n'est écrit."""
    devis_id, _payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert await _compter_checkouts(devis_id) == 0


async def test_ca1_checkout_cree_depuis_devis_accepte_avec_consentement(client, registered_user, organization):
    """CA-1 : devis `accepted` + consentement -> 201, checkout `open`, version 1, lié au devis."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["status"] == "open"
    assert corps["version"] == 1
    assert corps["quoteId"] == devis_id
    ligne = await _lire_checkout(corps["id"])
    assert ligne is not None and ligne["status"] == "open"


async def test_ca1_checkout_refuse_depuis_devis_non_accepte(client, registered_user, organization):
    """CA-1 : devis `priced` (non accepté) avec consentement -> INVALID_TRANSITION (409) ; rien n'est écrit."""
    devis_id, payeur_id = await _creer_devis_priced(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await _compter_checkouts(devis_id) == 0


async def test_ca1_checkout_refuse_depuis_devis_expire(client, registered_user, organization):
    """CA-1 : devis `priced` dont la date de validité est passée -> QUOTE_EXPIRED (422) ; rien n'est écrit."""
    devis_id, payeur_id = await _creer_devis_priced(client, registered_user, organization)
    await _poser_expiration_passee(devis_id)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "QUOTE_EXPIRED"
    assert await _compter_checkouts(devis_id) == 0


# --- CA-2 : le retour client ne passe pas le checkout à completed -----------------


async def test_ca2_le_client_ne_passe_pas_le_checkout_a_completed(client, registered_user, organization):
    """CA-2 : un corps qui annonce `status: completed` ne change rien ; le checkout reste `open`."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id, "status": "completed"}, headers=headers)

    assert res.status_code == 201, res.text
    checkout_id = res.json()["id"]
    assert res.json()["status"] == "open"
    relecture = await client.get(_url_checkout(checkout_id), headers=headers)
    assert relecture.json()["status"] == "open"
    assert (await _lire_checkout(checkout_id))["status"] == "open"


# --- CA-3 : permission d'acheteur --------------------------------------------------


async def test_ca3_checkout_refuse_sans_permission_d_acheteur(client, registered_user, organization):
    """CA-3 : un membre sans droit d'acheteur ne crée pas de checkout -> FORBIDDEN (403) ; rien n'est écrit."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    token_membre = await _ajouter_membre_sans_droit(client, organization["id"])
    headers = _entete(token_membre, organization["id"])

    res = await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert await _compter_checkouts(devis_id) == 0


# --- CA-4 : isolation tenant -------------------------------------------------------


async def test_ca4_checkout_du_tenant_a_traite_comme_inexistant_depuis_le_tenant_b(client, registered_user, organization):
    """CA-4 : lecture depuis le tenant B d'un checkout du tenant A -> 404, identique à un identifiant inconnu."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers_a = _entete(registered_user["accessToken"], organization["id"])
    checkout_id = (await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers_a)).json()["id"]

    # Tenant B réel dont l'utilisateur est propriétaire : la garde d'organisation laisse passer,
    # et c'est bien le service qui doit répondre comme à un checkout inexistant.
    res_tenant_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be081-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res_tenant_b.status_code in (200, 201), res_tenant_b.text
    headers_b = _entete(registered_user["accessToken"], res_tenant_b.json()["id"])

    res_existant = await client.get(_url_checkout(checkout_id), headers=headers_b)
    res_inconnu = await client.get(_url_checkout(str(uuid.uuid4())), headers=headers_b)

    assert res_existant.status_code == 404, res_existant.text
    assert res_inconnu.status_code == 404
    assert res_existant.json()["error"]["code"] == res_inconnu.json()["error"]["code"] == "checkout_not_found"


# --- Lecture et structure ----------------------------------------------------------


async def test_lecture_du_checkout_par_son_tenant(client, registered_user, organization):
    """Le tenant propriétaire lit son checkout (GET 200) avec son statut `open`."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers = _entete(registered_user["accessToken"], organization["id"])
    checkout_id = (await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers)).json()["id"]

    res = await client.get(_url_checkout(checkout_id), headers=headers)

    assert res.status_code == 200, res.text
    assert res.json()["id"] == checkout_id
    assert res.json()["status"] == "open"


async def test_lecture_du_checkout_refusee_sans_permission_de_lecture(client, registered_user, organization):
    """Un membre du tenant sans droit de lecture ne lit pas le checkout -> FORBIDDEN (403)."""
    devis_id, payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    await _consentir(payeur_id, await _id_utilisateur(registered_user["email"]))
    headers_proprietaire = _entete(registered_user["accessToken"], organization["id"])
    checkout_id = (await client.post(_url_checkout(), json={"quoteId": devis_id}, headers=headers_proprietaire)).json()["id"]
    token_membre = await _ajouter_membre_sans_droit(client, organization["id"])

    res = await client.get(_url_checkout(checkout_id), headers=_entete(token_membre, organization["id"]))

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"


async def test_table_checkout_a_les_colonnes_definies():
    """Définition : id, quoteId, status, version, createdAt. Aucune autre colonne (QE-FAC-04)."""
    async with engine.connect() as conn:
        resultat = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'checkout'"))
        colonnes = {ligne[0] for ligne in resultat}
    assert colonnes == {"id", "quoteId", "status", "version", "createdAt"}


async def test_table_checkout_refuse_un_statut_hors_machine_d_etat(client, registered_user, organization):
    """Statuts `open, pending, completed, failed, cancelled, expired` : tout autre statut est refusé par la base."""
    devis_id, _payeur_id = await _creer_devis_accepte(client, registered_user, organization)
    async with AsyncSessionLocal() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                text('INSERT INTO checkout (id, "quoteId", status, version, "createdAt") '
                     "VALUES (:id, :q, 'inconnu', 1, now())"),
                {"id": uuid.uuid4(), "q": uuid.UUID(devis_id)},
            )
            await db.commit()
