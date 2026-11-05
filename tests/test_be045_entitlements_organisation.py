"""BE-045 : entitlements organisation (source, période, quota).

Intention : prouver par des tests les critères d'acceptation de BE-045
(implementation-backend/tasks-modules-droits.md, section BE-045) :
- CA-1 : la migration ajoute à `subscription_entitlement` la colonne `stateVersion` et
  l'index (organizationId, moduleCode), et retire les valeurs par défaut implicites de
  `niveauApplication` (scope) et `sourceAttribution` (source) ;
- CA-2 (refus) : un membre sans `organization.entitlement.read` reçoit 403 ;
- CA-3 (isolation) : un membre de A appelant `/organizations/B/entitlements` reçoit 404
  et aucune donnée de B ;
- CA-4 : un entitlement sans `source` ou sans `scope` ne peut pas être enregistré ;
- CA-5 : une capacité sans `quotaUnit` renvoie `quotaUnit: null`, sans valeur inventée.

Route testée : GET /api/v1/organizations/{organization_id}/entitlements. Permission :
`organization.entitlement.read` (QE-MOD-16, portée organisation).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.billing import service
from app.billing.models import Capability, Subscription, SubscriptionEntitlement
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


async def _abonnement(organization_id: uuid.UUID) -> uuid.UUID:
    """Abonnement actif rattaché à un plan du catalogue ; retourne son identifiant."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be045-{uuid.uuid4().hex[:10]}", "Plan BE-045", 0, "XAF", 30
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


async def _capacite(quota_unit: str | None) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        capacite = Capability(
            moduleCode="zylo_liquid", code=f"be045.cap.{uuid.uuid4().hex[:10]}",
            name="Capacité BE-045", quotaUnit=quota_unit,
        )
        db.add(capacite)
        await db.commit()
        return capacite.id


async def _entitlement(organization_id: uuid.UUID, subscription_id: uuid.UUID, **champs) -> uuid.UUID:
    maintenant = datetime.now(timezone.utc)
    valeurs = {
        "organizationId": organization_id, "subscriptionId": subscription_id, "moduleCode": "zylo_liquid",
        "entitlementCode": f"be045.code.{uuid.uuid4().hex[:8]}", "status": "active",
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
        "email": f"be045-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-045",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def test_migration_ajoute_stateversion_index_et_retire_les_defauts(client: AsyncClient):
    """CA-1 : colonne `stateVersion`, index (organizationId, moduleCode), défauts implicites retirés."""
    async with AsyncSessionLocal() as db:
        colonnes = {
            ligne[0]: ligne[1]
            for ligne in (await db.execute(text(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'subscription_entitlement'"
            ))).all()
        }
        index = {
            ligne[0]
            for ligne in (await db.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'subscription_entitlement'"
            ))).all()
        }
    assert "stateVersion" in colonnes
    assert "ix_subscription_entitlement_organizationId_moduleCode" in index
    assert colonnes["niveauApplication"] is None
    assert colonnes["sourceAttribution"] is None


async def test_entitlement_sans_source_ni_scope_ne_peut_pas_etre_enregistre(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : sans `sourceAttribution` ou sans `niveauApplication`, la base refuse la ligne."""
    org_id = uuid.UUID(organization["id"])
    subscription_id = await _abonnement(org_id)
    for champ in ("sourceAttribution", "niveauApplication"):
        async with AsyncSessionLocal() as db:
            ligne = SubscriptionEntitlement(
                organizationId=org_id, subscriptionId=subscription_id, moduleCode="zylo_liquid",
                entitlementCode=f"be045.sans.{champ}", status="active",
                startsAt=datetime.now(timezone.utc),
                sourceAttribution="offre", niveauApplication="organisation",
            )
            setattr(ligne, champ, None)
            db.add(ligne)
            with pytest.raises(IntegrityError):
                await db.commit()


async def test_membre_sans_entitlement_read_recoit_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un membre sans `organization.entitlement.read` est refusé ; aucune donnée."""
    org_id = uuid.UUID(organization["id"])
    await _entitlement(org_id, await _abonnement(org_id), entitlementCode="be045.secret.code")
    token = await _membre_sans_droit(client, org_id)

    reponse = await client.get(f"/api/v1/organizations/{organization['id']}/entitlements",
                               headers=_entete(token, organization["id"]))

    assert reponse.status_code == 403
    assert "be045.secret.code" not in reponse.text


async def test_organisation_d_un_autre_tenant_repond_404_sans_donnee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : le membre de A appelant /organizations/B/entitlements reçoit 404 et rien de B.

    B est créée par un autre utilisateur : le créateur d'une organisation en
    devient propriétaire, donc le membre de A y aurait un accès légitime (200).
    """
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be045-proprio-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Proprietaire B BE-045",
    })
    login_autre = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res_b = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-045", "slug": f"be045-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login_autre.json()['accessToken']}"},
    )
    org_b = res_b.json()["id"]
    await _entitlement(uuid.UUID(org_b), await _abonnement(uuid.UUID(org_b)), entitlementCode="be045.donnee.b")
    headers_a = _entete(registered_user["accessToken"], organization["id"])

    reponse_path_b = await client.get(f"/api/v1/organizations/{org_b}/entitlements", headers=headers_a)
    reponse_header_b = await client.get(
        f"/api/v1/organizations/{org_b}/entitlements", headers=_entete(registered_user["accessToken"], org_b)
    )

    assert reponse_path_b.status_code == 404
    assert reponse_header_b.status_code == 404
    assert "be045.donnee.b" not in reponse_path_b.text
    assert "be045.donnee.b" not in reponse_header_b.text


async def test_proprietaire_lit_source_periode_quota_et_etat(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Lecture nominale : chaque entitlement expose état, source, période et limite."""
    org_id = uuid.UUID(organization["id"])
    subscription_id = await _abonnement(org_id)
    maintenant = datetime.now(timezone.utc)
    await _entitlement(
        org_id, subscription_id, entitlementCode="be045.lecture", quotaLimite=5,
        startsAt=maintenant, endsAt=maintenant + timedelta(days=10),
    )

    reponse = await client.get(f"/api/v1/organizations/{organization['id']}/entitlements",
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200
    ligne = next(item for item in reponse.json()["included"] if item["entitlementCode"] == "be045.lecture")
    assert ligne["source"] == "offre"
    assert ligne["scope"] == "organisation"
    assert ligne["state"] == "active"
    assert ligne["quotaLimit"] == 5
    assert ligne["periodStart"] is not None
    assert ligne["periodEnd"] is not None
    assert ligne["stateVersion"] == 1


async def test_quota_unit_absent_renvoie_null_sans_valeur_inventee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : une capacité sans `quotaUnit` donne `quotaUnit: null`."""
    org_id = uuid.UUID(organization["id"])
    capacite_id = await _capacite(None)
    await _entitlement(
        org_id, await _abonnement(org_id), entitlementCode="be045.sans.unite",
        capaciteId=capacite_id, quotaLimite=3,
    )

    reponse = await client.get(f"/api/v1/organizations/{organization['id']}/entitlements",
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    ligne = next(item for item in reponse.json()["included"] if item["entitlementCode"] == "be045.sans.unite")
    assert ligne["quotaUnit"] is None
