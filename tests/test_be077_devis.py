"""BE-077 : devis (Quote) : création, lecture, acceptation.

Intention : prouver les critères d'acceptation de BE-077
(implementation-backend/tasks-abonnements-facturation.md, section BE-077) :
- CA-1 : un devis `created` sans prix configuré reste `created` ; la réponse porte
  `PRICE_NOT_CONFIGURED` ; une fois le prix configuré, le devis passe en `priced`
  et capture le snapshot de prix (BE-078) ;
- CA-2 : `accept` sur un devis expiré renvoie `QUOTE_EXPIRED` et ne crée aucune
  souscription ;
- CA-3 : `POST` et `accept` sans permission d'acheteur renvoient `FORBIDDEN` ;
- CA-4 : `GET` d'un devis du tenant A depuis le tenant B répond comme un devis
  inexistant (404 `quote_not_found`).

Hors CA, ces tests couvrent la machine d'état (`accept` depuis `created` ->
`INVALID_TRANSITION`, acceptation nominale, `VERSION_CONFLICT` sur `expectedVersion`
obsolète) et la structure de la table `quote`.

Décisions consignées (voir QE-FAC-04, QE-FAC-10, QE-FAC-21) : la durée d'expiration
n'est pas définie ; le test pose `expiresAt` directement en base. Le scénario de
tarification est fourni par l'appelant (valeur non définie).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.billing import service
from app.billing.models import Subscription
from app.billing.payers import creer_payeur
from app.billing.pricing.resolution import definir_regle_prix
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, OrganizationUser, User

SCENARIO = "achat"
MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


# --- aides ------------------------------------------------------------------------


def _url(quote_id: str | None = None, action: str | None = None) -> str:
    base = "/api/v1/billing/quotes"
    if quote_id is None:
        return base
    return f"{base}/{quote_id}" if action is None else f"{base}/{quote_id}/{action}"


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _inscrire_et_connecter(client, email: str) -> str:
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acheteur"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return login.json()["accessToken"]


async def _creer_plan_et_payeur() -> tuple[str, uuid.UUID]:
    """Offre du catalogue (zylo_liquid, prix de référence) et compte payeur."""
    async with AsyncSessionLocal() as db:
        code = f"be077-{uuid.uuid4().hex[:8]}"
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-077", 1000, "XAF", 30)
        payeur = await creer_payeur(db, "organisation", f"compte-{uuid.uuid4().hex[:8]}")
        return code, payeur.id


async def _definir_prix(tenant_id: uuid.UUID, plan_code: str, montant: int = 5000, devise: str = "XAF", taux_bps: int = 1925) -> None:
    async with AsyncSessionLocal() as db:
        await definir_regle_prix(
            db,
            organization_id=tenant_id,
            object_code=plan_code,
            scenario=SCENARIO,
            amount_minor=montant,
            currency=devise,
            tax_rate_bps=taux_bps,
        )


async def _lire_devis(quote_id: str) -> dict | None:
    """Lecture brute de la ligne `quote` (le test ne dépend pas du modèle ORM)."""
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(text("SELECT * FROM quote WHERE id = :id"), {"id": uuid.UUID(quote_id)})).mappings().first()
        return dict(ligne) if ligne is not None else None


async def _compter_souscriptions(tenant_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(select(Subscription).where(Subscription.organizationId == tenant_id))).all())


async def _poser_expiration_passee(quote_id: str) -> None:
    """La durée d'expiration n'est pas définie (QE-FAC-21) : on fixe une date passée en base."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE quote SET \"expiresAt\" = :passe WHERE id = :id"),
            {"passe": datetime.now(timezone.utc) - timedelta(days=1), "id": uuid.UUID(quote_id)},
        )
        await db.commit()


async def _creer_devis_priced(client, registered_user, organization) -> str:
    """Devis `priced` pour le tenant, créé par l'acheteur (propriétaire)."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    await _definir_prix(uuid.UUID(organization["id"]), plan_code)
    headers = _entete(registered_user["accessToken"], organization["id"])
    res = await client.post(_url(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


# --- CA-1 : prix non configuré, puis configuré -------------------------------------


async def test_ca1_sans_prix_configure_le_devis_reste_created_et_la_reponse_porte_price_not_configured(client, registered_user, organization):
    """CA-1 : pas de règle de prix -> PRICE_NOT_CONFIGURED ; le devis est persisté en `created`."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers)

    assert res.status_code == 422, res.text
    corps = res.json()
    assert corps["error"]["code"] == "PRICE_NOT_CONFIGURED"
    devis_id = corps["error"]["details"][0]["quoteId"]
    ligne = await _lire_devis(devis_id)
    assert ligne is not None
    assert ligne["status"] == "created"
    assert ligne["beneficiaryTenantId"] == uuid.UUID(organization["id"])
    assert ligne["pricingSnapshotJson"] is None


async def test_ca1_prix_configure_passe_en_priced_et_capture_le_snapshot(client, registered_user, organization):
    """CA-1 (suite) : règle configurée -> 201, statut `priced`, snapshot de prix capturé au devis."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    tenant_id = uuid.UUID(organization["id"])
    await _definir_prix(tenant_id, plan_code, montant=5000, devise="XAF", taux_bps=1925)
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers)

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["status"] == "priced"
    ligne = await _lire_devis(corps["id"])
    assert ligne["status"] == "priced"
    snapshot = ligne["pricingSnapshotJson"]
    assert snapshot["amountMinor"] == 5000
    assert snapshot["currency"] == "XAF"
    assert snapshot["taxRateBps"] == 1925
    assert snapshot["objectCode"] == plan_code


# --- CA-2 : devis expiré -----------------------------------------------------------


async def test_ca2_accept_sur_devis_expire_renvoie_quote_expired_sans_souscription(client, registered_user, organization):
    """CA-2 : devis dont la date de validité est passée -> QUOTE_EXPIRED ; aucune souscription créée."""
    tenant_id = uuid.UUID(organization["id"])
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    await _poser_expiration_passee(devis_id)
    headers = _entete(registered_user["accessToken"], organization["id"])
    souscriptions_avant = await _compter_souscriptions(tenant_id)

    res = await client.post(_url(devis_id, "accept"), json={}, headers=headers)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "QUOTE_EXPIRED"
    assert await _compter_souscriptions(tenant_id) == souscriptions_avant
    assert (await _lire_devis(devis_id))["status"] == "expired"


# --- CA-3 : refus sans permission d'acheteur ---------------------------------------


async def test_ca3_creation_refusee_sans_permission_d_acheteur(client, registered_user, organization):
    """CA-3 : un membre sans droit ne crée pas de devis -> FORBIDDEN."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    email_membre = f"be077-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User).where(User.email == email_membre))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=membre.id))
        await db.commit()
    headers = _entete(token_membre, organization["id"])

    res = await client.post(_url(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"


async def test_ca3_acceptation_refusee_sans_permission_d_acheteur_et_devis_inchange(client, registered_user, organization):
    """CA-3 : un membre sans droit n'accepte pas le devis ; le devis reste `priced`."""
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    email_membre = f"be077-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User).where(User.email == email_membre))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=membre.id))
        await db.commit()
    headers = _entete(token_membre, organization["id"])

    res = await client.post(_url(devis_id, "accept"), json={}, headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert (await _lire_devis(devis_id))["status"] == "priced"


# --- CA-4 : isolation tenant -------------------------------------------------------


async def test_ca4_devis_du_tenant_a_traite_comme_inexistant_depuis_le_tenant_b(client, registered_user, organization):
    """CA-4 : lecture depuis le tenant B d'un devis du tenant A -> 404, identique à un identifiant inconnu."""
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    # Tenant B réel dont l'utilisateur est propriétaire : la garde d'organisation laisse passer,
    # et c'est bien le service qui doit répondre comme à un devis inexistant.
    res_tenant_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be077-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res_tenant_b.status_code in (200, 201), res_tenant_b.text
    headers = _entete(registered_user["accessToken"], res_tenant_b.json()["id"])

    res_existant = await client.get(_url(devis_id), headers=headers)
    res_inconnu = await client.get(_url(str(uuid.uuid4())), headers=headers)

    assert res_existant.status_code == 404, res_existant.text
    assert res_inconnu.status_code == 404
    assert res_existant.json()["error"]["code"] == res_inconnu.json()["error"]["code"] == "quote_not_found"


async def test_lecture_du_devis_par_son_tenant(client, registered_user, organization):
    """Le tenant propriétaire lit son devis (GET 200) avec son statut."""
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.get(_url(devis_id), headers=headers)

    assert res.status_code == 200, res.text
    assert res.json()["id"] == devis_id
    assert res.json()["status"] == "priced"


# --- Machine d'état et verrou optimiste --------------------------------------------


async def test_accept_depuis_created_renvoie_invalid_transition(client, registered_user, organization):
    """Un devis `created` (sans prix) ne peut pas être accepté -> INVALID_TRANSITION, pas de changement."""
    plan_code, payeur_id = await _creer_plan_et_payeur()
    headers = _entete(registered_user["accessToken"], organization["id"])
    res_creation = await client.post(_url(), json={"planCode": plan_code, "scenario": SCENARIO, "payerId": str(payeur_id)}, headers=headers)
    devis_id = res_creation.json()["error"]["details"][0]["quoteId"]

    res = await client.post(_url(devis_id, "accept"), json={}, headers=headers)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "INVALID_TRANSITION"
    assert (await _lire_devis(devis_id))["status"] == "created"


async def test_accept_nominal_passe_en_accepted_et_incremente_la_version(client, registered_user, organization):
    """Devis `priced` valide -> 200, statut `accepted`, version incrémentée."""
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    avant = await _lire_devis(devis_id)
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url(devis_id, "accept"), json={}, headers=headers)

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "accepted"
    apres = await _lire_devis(devis_id)
    assert apres["status"] == "accepted"
    assert apres["version"] == avant["version"] + 1


async def test_accept_avec_version_attendue_obsolete_renvoie_version_conflict(client, registered_user, organization):
    """`expectedVersion` ne correspondant plus à la version courante -> VERSION_CONFLICT, rien n'est modifié."""
    devis_id = await _creer_devis_priced(client, registered_user, organization)
    version_courante = (await _lire_devis(devis_id))["version"]
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.post(_url(devis_id, "accept"), json={"expectedVersion": version_courante + 5}, headers=headers)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "VERSION_CONFLICT"
    assert (await _lire_devis(devis_id))["status"] == "priced"


# --- Structure de la table ---------------------------------------------------------


async def test_table_quote_a_les_colonnes_definies():
    """Définition : id, payerId, beneficiaryTenantId, planVersionSnapshotId, status, version, expiresAt, createdAt ;
    `pricingSnapshotJson` ajouté pour le snapshot de prix (BE-078, CA-2)."""
    async with engine.connect() as conn:
        resultat = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'quote'"))
        colonnes = {ligne[0] for ligne in resultat}
    assert colonnes == {
        "id", "payerId", "beneficiaryTenantId", "planVersionSnapshotId",
        "status", "version", "expiresAt", "createdAt", "pricingSnapshotJson",
    }
