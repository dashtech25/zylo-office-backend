"""BE-026 : abonnement et droits de l'organisation courante (lecture).

Intention : prouver par des tests les critères d'acceptation de BE-026
(implementation-backend/tasks-socle-tenant-identite.md, section BE-026) :
- CA-1 : une organisation sans abonnement reçoit un état vide, sans plan ni facture inventés ;
- CA-2 (refus) : un membre sans permission de lecture de la facturation reçoit 403 ;
- CA-3 (isolation) : l'abonnement de O2 n'est jamais retourné à O1 ;
- CA-4 : la réponse ne contient aucun identifiant ou secret du fournisseur de paiement.

Routes testées : GET /api/v1/organizations/current/subscription et
GET /api/v1/organizations/current/entitlements, organisation résolue par l'en-tête
X-Organization-Id (membership actif requis). Permission : `billing.subscription.read`
(recommandation appliquée à QE-SOC-06).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import Invoice, Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, OrganizationUser


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


async def _creer_organisation(nom: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=nom, slug=f"be026-{uuid.uuid4().hex[:12]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _ajouter_membre(user_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Rattache un utilisateur à une organisation sans aucun rôle (aucune permission)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=user_id))
        await db.commit()


async def _abonnement_actif(organization_id: uuid.UUID, entitlement_codes: list[str], *, endsAt=None) -> uuid.UUID:
    """Abonnement actif rattaché à un plan du catalogue, avec des entitlements actifs."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be026-{uuid.uuid4().hex[:10]}", "Plan BE-026", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        maintenant = datetime.now(timezone.utc)
        subscription = Subscription(
            organizationId=organization_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(subscription)
        await db.flush()
        for code in entitlement_codes:
            db.add(SubscriptionEntitlement(
                organizationId=organization_id, subscriptionId=subscription.id, moduleCode="zylo_liquid",
                entitlementCode=code, status="active", startsAt=maintenant,
                endsAt=endsAt or maintenant + timedelta(days=30),
                sourceAttribution="offre", niveauApplication="organisation",
            ))
        await db.commit()
        return subscription.id


async def _compter(modele, organization_id: uuid.UUID | None = None) -> int:
    async with AsyncSessionLocal() as db:
        requete = select(func.count()).select_from(modele)
        if organization_id is not None and modele is Subscription:
            requete = requete.where(Subscription.organizationId == organization_id)
        if organization_id is not None and modele is Invoice:
            requete = requete.join(Subscription, Subscription.id == Invoice.subscriptionId).where(
                Subscription.organizationId == organization_id
            )
        return await db.scalar(requete)


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def test_organisation_sans_abonnement_recoit_un_etat_vide(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : aucun plan, aucune facture ni abonnement n'est inventé à la lecture."""
    headers = _entete(registered_user["accessToken"], organization["id"])
    org_id = uuid.UUID(organization["id"])

    subscription = await client.get("/api/v1/organizations/current/subscription", headers=headers)
    entitlements = await client.get("/api/v1/organizations/current/entitlements", headers=headers)

    assert subscription.status_code == 200
    assert subscription.json() is None
    assert entitlements.status_code == 200
    assert entitlements.json() == []
    assert await _compter(Subscription, org_id) == 0
    assert await _compter(Invoice, org_id) == 0


async def test_membre_sans_permission_de_lecture_recoit_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un membre sans rôle (donc sans `billing.subscription.read`) est refusé."""
    org_id = uuid.UUID(organization["id"])
    await _abonnement_actif(org_id, ["zylo_liquid.access"])
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": "TestPassword123!", "fullName": "Membre Sans Droit",
    })
    email = membre.json()["email"]
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"})
    token = login.json()["accessToken"]
    user_id = uuid.UUID(membre.json()["id"])
    await _ajouter_membre(user_id, org_id)

    subscription = await client.get(
        "/api/v1/organizations/current/subscription", headers=_entete(token, organization["id"])
    )
    entitlements = await client.get(
        "/api/v1/organizations/current/entitlements", headers=_entete(token, organization["id"])
    )

    assert subscription.status_code == 403
    assert entitlements.status_code == 403


async def test_abonnement_d_une_autre_organisation_jamais_retourne(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : l'abonnement et les entitlements de O2 ne sortent jamais sous O1."""
    headers_o1 = _entete(registered_user["accessToken"], organization["id"])
    res_o2 = await client.post(
        "/api/v1/organizations", json={"name": "Autre Org", "slug": f"autre-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    o2_id = res_o2.json()["id"]
    await _abonnement_actif(uuid.UUID(o2_id), ["zylo_liquid.o2_seulement"])

    sous_o1_sub = await client.get("/api/v1/organizations/current/subscription", headers=headers_o1)
    sous_o1_ent = await client.get("/api/v1/organizations/current/entitlements", headers=headers_o1)
    sous_o2_sub = await client.get(
        "/api/v1/organizations/current/subscription", headers=_entete(registered_user["accessToken"], o2_id)
    )

    assert sous_o1_sub.json() is None
    assert all(e["entitlementCode"] != "zylo_liquid.o2_seulement" for e in sous_o1_ent.json())
    assert sous_o2_sub.status_code == 200
    assert sous_o2_sub.json()["organizationId"] == o2_id


async def test_non_membre_de_l_organisation_demandee_recoit_404(
    client: AsyncClient, registered_user: dict
):
    """CA-3 : un utilisateur qui n'est pas membre de l'organisation demandée reçoit 404, sans fuite."""
    autre_org = await _creer_organisation("Org Etrangere")
    await _abonnement_actif(autre_org, ["zylo_liquid.etranger"])

    res = await client.get(
        "/api/v1/organizations/current/subscription",
        headers=_entete(registered_user["accessToken"], str(autre_org)),
    )

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"


async def test_reponse_sans_identifiant_ni_secret_fournisseur(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : aucun identifiant ni secret du fournisseur de paiement dans les réponses."""
    await _abonnement_actif(uuid.UUID(organization["id"]), ["zylo_liquid.access"])
    headers = _entete(registered_user["accessToken"], organization["id"])

    subscription = await client.get("/api/v1/organizations/current/subscription", headers=headers)
    entitlements = await client.get("/api/v1/organizations/current/entitlements", headers=headers)

    assert subscription.status_code == 200
    assert entitlements.status_code == 200
    for corps in (subscription.text, entitlements.text):
        for interdit in ("flutterwave", "providerReference", "secret", "FLUTTERWAVE", "verif"):
            assert interdit not in corps
    assert set(subscription.json().keys()) == {
        "id", "organizationId", "planId", "planVersionId", "status", "startDate", "endDate", "entitlementCodes",
    }


async def test_entitlements_affichent_l_etat_calcule(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Un entitlement dont la date de fin est passée est lu `expired` ; un actif reste `active`."""
    org_id = uuid.UUID(organization["id"])
    await _abonnement_actif(org_id, ["zylo_liquid.actif"])
    await _abonnement_actif(org_id, ["zylo_liquid.perime"], endsAt=datetime.now(timezone.utc) - timedelta(days=1))
    headers = _entete(registered_user["accessToken"], organization["id"])

    res = await client.get("/api/v1/organizations/current/entitlements", headers=headers)

    assert res.status_code == 200
    etats = {e["entitlementCode"]: e["etat"] for e in res.json()}
    assert etats == {"zylo_liquid.actif": "active", "zylo_liquid.perime": "expired"}
