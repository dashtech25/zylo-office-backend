"""BE-107 : lecture des entitlements et modules activés (droits inclus et add-ons séparés).

Intention : prouver par des tests les critères d'acceptation de BE-107
(implementation-backend/tasks-portail-organisation.md, section BE-107) :
- CA-1 : la réponse sépare les droits inclus et les add-ons dans deux groupes distincts ;
- CA-2 : sans la permission de lecture des entitlements, 403 ;
- CA-3 : organisation hors portée, 404 et aucune donnée d'entitlement (isolation tenant) ;
- CA-4 : POST, PATCH ou DELETE sur la route sont refusés et ne modifient rien.

Route testée : GET /api/v1/organizations/{organization_id}/entitlements.
Permission : `organization.entitlement.read` (écart documenté : la fiche écrit
`entitlement:read`, format absent du dépôt ; voir app/billing/permissions.py).
Groupe « inclus » : `sourceAttribution` = `offre` ; groupe « add-ons » : toute autre source.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/entitlements"


async def _abonnement(organization_id: uuid.UUID) -> uuid.UUID:
    """Abonnement actif rattaché à un plan du catalogue ; retourne son identifiant."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be107-{uuid.uuid4().hex[:10]}", "Plan BE-107", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        maintenant = datetime.now(timezone.utc)
        subscription = Subscription(
            organizationId=organization_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(subscription)
        await db.commit()
        return subscription.id


async def _entitlement(organization_id: uuid.UUID, subscription_id: uuid.UUID, **champs) -> uuid.UUID:
    """Ligne d'entitlement de l'organisation ; par défaut un droit inclus à l'offre."""
    maintenant = datetime.now(timezone.utc)
    valeurs = {
        "organizationId": organization_id, "subscriptionId": subscription_id, "moduleCode": "zylo_liquid",
        "entitlementCode": f"be107.code.{uuid.uuid4().hex[:8]}", "status": "active",
        "startsAt": maintenant, "endsAt": maintenant + timedelta(days=30),
        "sourceAttribution": "offre", "niveauApplication": "organisation",
    }
    valeurs.update(champs)
    async with AsyncSessionLocal() as db:
        ligne = SubscriptionEntitlement(**valeurs)
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Crée un utilisateur rattaché à l'organisation sans rôle ; retourne son jeton."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be107-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-107",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _nombre_entitlements(organization_id: uuid.UUID) -> int:
    """Nombre de lignes d'entitlement de l'organisation, lu directement en base."""
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(SubscriptionEntitlement)
            .where(SubscriptionEntitlement.organizationId == organization_id)
        )).scalar_one()


async def test_reponse_separe_droits_inclus_et_addons_en_deux_groupes(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : la réponse porte deux groupes distincts, `included` (offre) et `addOns` (autre source)."""
    org_id = uuid.UUID(organization["id"])
    subscription_id = await _abonnement(org_id)
    await _entitlement(org_id, subscription_id, entitlementCode="be107.inclus.offre", sourceAttribution="offre")
    await _entitlement(org_id, subscription_id, entitlementCode="be107.addon.achat",
                       sourceAttribution="achat_additionnel")

    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200
    corps = reponse.json()
    assert set(corps.keys()) == {"included", "addOns"}
    codes_inclus = {ligne["entitlementCode"] for ligne in corps["included"]}
    codes_addons = {ligne["entitlementCode"] for ligne in corps["addOns"]}
    assert "be107.inclus.offre" in codes_inclus
    assert "be107.addon.achat" in codes_addons
    assert codes_inclus.isdisjoint(codes_addons)
    assert "be107.addon.achat" not in codes_inclus
    assert "be107.inclus.offre" not in codes_addons


async def test_membre_sans_permission_de_lecture_recoit_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un membre sans permission de lecture des entitlements est refusé ; aucune donnée."""
    org_id = uuid.UUID(organization["id"])
    await _entitlement(org_id, await _abonnement(org_id), entitlementCode="be107.secret.code")
    token = await _membre_sans_droit(client, org_id)

    reponse = await client.get(_url(organization["id"]), headers=_entete(token, organization["id"]))

    assert reponse.status_code == 403
    assert "be107.secret.code" not in reponse.text


async def test_organisation_hors_portee_repond_404_sans_donnee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : le membre de A appelant la route de B reçoit 404 et aucune donnée de B."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be107-proprio-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Proprietaire B BE-107",
    })
    login_autre = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res_b = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-107", "slug": f"be107-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login_autre.json()['accessToken']}"},
    )
    org_b = res_b.json()["id"]
    await _entitlement(uuid.UUID(org_b), await _abonnement(uuid.UUID(org_b)), entitlementCode="be107.donnee.b")

    reponse = await client.get(_url(org_b), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 404
    assert "be107.donnee.b" not in reponse.text


async def test_ecriture_sur_la_route_est_refusee_et_ne_modifie_rien(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : POST, PATCH et DELETE sur la route sont refusés ; aucune ligne créée, modifiée ou supprimée."""
    org_id = uuid.UUID(organization["id"])
    await _entitlement(org_id, await _abonnement(org_id), entitlementCode="be107.intact")
    nombre_avant = await _nombre_entitlements(org_id)
    entete = _entete(registered_user["accessToken"], organization["id"])

    reponses = [
        await client.post(_url(organization["id"]), json={"entitlementCode": "be107.ecrit"}, headers=entete),
        await client.patch(_url(organization["id"]), json={"entitlementCode": "be107.modifie"}, headers=entete),
        await client.delete(_url(organization["id"]), headers=entete),
    ]

    for reponse in reponses:
        assert reponse.status_code == 405
    assert await _nombre_entitlements(org_id) == nombre_avant
