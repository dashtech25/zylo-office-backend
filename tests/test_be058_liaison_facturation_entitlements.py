"""BE-058 : liaison facturation vers entitlements (événements de service).

Intention : prouver par des tests les critères d'acceptation de BE-058
(implementation-backend/tasks-modules-droits.md, section BE-058) :
- CA-1 : un événement `granted` crée ou met à jour l'entitlement avec la source reçue ;
- CA-2 : un événement dupliqué (même `eventId`) ne produit aucun second effet ;
- CA-3 (refus) : un appelant sans identité de service reçoit 403 ; rien n'est modifié ;
- CA-4 : un événement de fin d'abonnement passe l'entitlement à `expired` ; le cas impayé
  n'est pas décidé et renvoie `reconciliation_required` (QE-MOD-06, défaut appliqué) ;
- CA-5 : un événement pour une organisation inconnue renvoie 404 et est journalisé.

Route testée : POST /api/v1/internal/billing/entitlement-events (QE-MOD-01, recommandation
appliquée). Identité de service : en-tête `X-Service-Token` comparé à la variable
`BILLING_SERVICE_TOKEN` (QE-MOD-18, hypothèse appliquée ; échec fermé si la variable est vide).

Les valeurs attendues sont des littéraux tirés de la définition, jamais recalculées.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.billing import service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization

JETON_SERVICE = "jeton-service-be058-de-test-32-caracteres"
ROUTE = "/api/v1/internal/billing/entitlement-events"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


@pytest.fixture
def identite_service(monkeypatch):
    """Active l'identité de service pour le test (jeton de test, hors dépôt)."""
    monkeypatch.setenv("BILLING_SERVICE_TOKEN", JETON_SERVICE)
    return {"X-Service-Token": JETON_SERVICE}


async def _organisation_et_abonnement() -> tuple[uuid.UUID, uuid.UUID]:
    """Crée une organisation et un abonnement actif ; retourne (organisation_id, subscription_id)."""
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            'INSERT INTO module (id, code, name, version, "createdAt", "updatedAt") '
            "VALUES (:id, 'zylo_liquid', 'Zylo Liquid', '0.1.0', now(), now()) ON CONFLICT (code) DO NOTHING"
        ), {"id": uuid.uuid4()})
        organisation = Organization(name="Org BE-058", slug=f"be058-{uuid.uuid4().hex[:12]}", status="active")
        db.add(organisation)
        await db.flush()
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be058-{uuid.uuid4().hex[:10]}", "Plan BE-058", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        maintenant = datetime.now(timezone.utc)
        subscription = Subscription(
            organizationId=organisation.id, planId=plan.id, planVersionId=version.id, status="active",
            startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(subscription)
        await db.commit()
        return organisation.id, subscription.id


def _evenement_granted(organisation_id, subscription_id, code: str, **champs) -> dict:
    """Corps d'un événement `granted` ; `champs` remplace les valeurs par défaut."""
    corps = {
        "eventId": f"evt-{uuid.uuid4().hex}",
        "type": "granted",
        "organizationId": str(organisation_id),
        "subscriptionId": str(subscription_id),
        "moduleCode": "zylo_liquid",
        "entitlementCode": code,
        "sourceAttribution": "achat_additionnel",
        "niveauApplication": "organisation",
        "startsAt": datetime.now(timezone.utc).isoformat(),
        "endsAt": None,
        "quotaLimite": 10,
    }
    corps.update(champs)
    return corps


def _evenement_ended(organisation_id, subscription_id, code: str, cause: str = "fin_abonnement") -> dict:
    return {
        "eventId": f"evt-{uuid.uuid4().hex}",
        "type": "ended",
        "organizationId": str(organisation_id),
        "subscriptionId": str(subscription_id),
        "moduleCode": "zylo_liquid",
        "entitlementCode": code,
        "endedAt": datetime.now(timezone.utc).isoformat(),
        "cause": cause,
    }


async def _entitlement(organisation_id: uuid.UUID, code: str) -> SubscriptionEntitlement | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(SubscriptionEntitlement).where(
            SubscriptionEntitlement.organizationId == organisation_id,
            SubscriptionEntitlement.entitlementCode == code,
        ))


async def _nombre_entitlements() -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(select(SubscriptionEntitlement.id))).all())


# --- CA-1 : granted crée puis met à jour, avec la source reçue --------------------------


@pytest.mark.asyncio
async def test_ca1_granted_cree_puis_met_a_jour_avec_la_source_recue(client: AsyncClient, identite_service):
    """CA-1 : le premier `granted` crée la ligne avec la source reçue (`achat_additionnel`,
    version d'état 1) ; un second `granted` sur le même code la met à jour (version 2)."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.ca1"

    premier = await client.post(ROUTE, json=_evenement_granted(organisation_id, subscription_id, code), headers=identite_service)
    assert premier.status_code == 200, premier.text
    cree = await _entitlement(organisation_id, code)
    assert cree is not None
    assert cree.sourceAttribution == "achat_additionnel"
    assert cree.status == "active"
    assert cree.stateVersion == 1

    second = await client.post(
        ROUTE, json=_evenement_granted(organisation_id, subscription_id, code, quotaLimite=20), headers=identite_service,
    )
    assert second.status_code == 200, second.text
    maj = await _entitlement(organisation_id, code)
    assert maj.id == cree.id
    assert maj.quotaLimite == 20
    assert maj.stateVersion == 2


@pytest.mark.asyncio
async def test_ca1_source_hors_liste_est_refusee_sans_effet(client: AsyncClient, identite_service):
    """CA-1 (garde) : une source absente de SOURCES_ATTRIBUTION renvoie 422, rien n'est écrit."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.source-inconnue"
    avant = await _nombre_entitlements()

    reponse = await client.post(
        ROUTE,
        json=_evenement_granted(organisation_id, subscription_id, code, sourceAttribution="cadeau"),
        headers=identite_service,
    )

    assert reponse.status_code == 422, reponse.text
    assert await _nombre_entitlements() == avant
    assert await _entitlement(organisation_id, code) is None


# --- CA-2 : idempotence par eventId -----------------------------------------------------


@pytest.mark.asyncio
async def test_ca2_evenement_duplique_ne_produit_aucun_second_effet(client: AsyncClient, identite_service):
    """CA-2 : rejouer le même `eventId` répond `duplicate` et ne change ni la version d'état
    ni le nombre d'entitlements."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.ca2"
    corps = _evenement_granted(organisation_id, subscription_id, code)

    premiere = await client.post(ROUTE, json=corps, headers=identite_service)
    assert premiere.status_code == 200, premiere.text
    assert premiere.json()["duplicate"] is False
    apres_premier = await _entitlement(organisation_id, code)
    avant_rejeu = await _nombre_entitlements()

    rejeu = await client.post(ROUTE, json=corps, headers=identite_service)

    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["duplicate"] is True
    assert await _nombre_entitlements() == avant_rejeu
    apres_rejeu = await _entitlement(organisation_id, code)
    assert apres_rejeu.stateVersion == apres_premier.stateVersion == 1


# --- CA-3 : identité de service obligatoire ---------------------------------------------


@pytest.mark.asyncio
async def test_ca3_sans_identite_de_service_renvoie_403_sans_modification(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    """CA-3 : sans jeton de service, avec un jeton erroné, avec un jeton utilisateur, ou quand
    `BILLING_SERVICE_TOKEN` n'est pas configurée (échec fermé), la route renvoie 403 et
    n'écrit aucun entitlement."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.ca3"
    corps = _evenement_granted(organisation_id, subscription_id, code)
    avant = await _nombre_entitlements()

    monkeypatch.setenv("BILLING_SERVICE_TOKEN", JETON_SERVICE)
    sans_jeton = await client.post(ROUTE, json=corps)
    jeton_faux = await client.post(ROUTE, json=corps, headers={"X-Service-Token": "mauvais-jeton"})
    jeton_utilisateur = await client.post(
        ROUTE, json=corps, headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    monkeypatch.setenv("BILLING_SERVICE_TOKEN", "")
    non_configure = await client.post(ROUTE, json=corps, headers={"X-Service-Token": ""})

    for reponse in (sans_jeton, jeton_faux, jeton_utilisateur, non_configure):
        assert reponse.status_code == 403, reponse.text
    assert await _nombre_entitlements() == avant
    assert await _entitlement(organisation_id, code) is None


# --- CA-4 : fin d'abonnement, cas impayé non décidé -------------------------------------


@pytest.mark.asyncio
async def test_ca4_fin_d_abonnement_passe_l_entitlement_a_expired(client: AsyncClient, identite_service):
    """CA-4 : après un `granted`, un `ended` de cause `fin_abonnement` passe le statut à `expired`."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.ca4"
    await client.post(ROUTE, json=_evenement_granted(organisation_id, subscription_id, code), headers=identite_service)

    reponse = await client.post(
        ROUTE, json=_evenement_ended(organisation_id, subscription_id, code), headers=identite_service,
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["outcome"] == "applied"
    assert (await _entitlement(organisation_id, code)).status == "expired"


@pytest.mark.asyncio
async def test_ca4_cas_impaye_renvoie_reconciliation_required_sans_decision(client: AsyncClient, identite_service):
    """CA-4 (impayé) : la règle d'impayé n'est pas décidée (QE-MOD-06) ; `ended` de cause
    `impaye` renvoie `reconciliation_required` et laisse le statut `active` inchangé."""
    organisation_id, subscription_id = await _organisation_et_abonnement()
    code = "ent.be058.ca4-impaye"
    await client.post(ROUTE, json=_evenement_granted(organisation_id, subscription_id, code), headers=identite_service)

    reponse = await client.post(
        ROUTE, json=_evenement_ended(organisation_id, subscription_id, code, cause="impaye"), headers=identite_service,
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["outcome"] == "reconciliation_required"
    assert (await _entitlement(organisation_id, code)).status == "active"


# --- CA-5 : organisation inconnue -------------------------------------------------------


@pytest.mark.asyncio
async def test_ca5_organisation_inconnue_renvoie_404_et_est_journalisee(client: AsyncClient, identite_service):
    """CA-5 : une organisation inexistante renvoie 404 ; l'événement est journalisé dans
    `entitlement_source_events` avec l'issue `organisation_inconnue` et aucun entitlement n'est créé."""
    _, subscription_id = await _organisation_et_abonnement()
    organisation_inconnue = uuid.uuid4()
    corps = _evenement_granted(organisation_inconnue, subscription_id, "ent.be058.ca5")
    avant = await _nombre_entitlements()

    reponse = await client.post(ROUTE, json=corps, headers=identite_service)

    assert reponse.status_code == 404, reponse.text
    assert await _nombre_entitlements() == avant
    async with engine.connect() as conn:
        ligne = (await conn.execute(
            text("SELECT outcome FROM entitlement_source_events WHERE \"eventId\" = :e"), {"e": corps["eventId"]},
        )).first()
    assert ligne is not None
    assert ligne[0] == "organisation_inconnue"
