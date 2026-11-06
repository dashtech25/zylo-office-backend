"""BE-131 : listes filtrées des objets de support (lecture).

Tests écrits d'après la définition `### BE-131` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes : `GET /api/v1/admin/organizations/{organization_id}/<liste>` pour
`subscriptions`, `invoices`, `payments`, `entitlements` et `incidents`.

Couverture :
- CA-1 : le registre couvre exactement les cinq listes, et chaque liste renvoie
  l'objet créé pour l'organisation (test de couverture) ;
- CA-2 : un filtre hors liste blanche de l'objet renvoie 422 ; une période
  inversée aussi ; les filtres `status`, `dateFrom`, `dateTo` et `id` marchent ;
- CA-3 (isolation tenant) : un agent de portée `tenant:A` qui demande la liste
  du tenant B reçoit 403 ; sa propre liste ne contient que ses objets ; la
  liste des incidents n'est pas servie en portée tenant (BE-247 CA-3) ;
- CA-4 (refus de droit) : un rôle sans autorité plateforme (`agent_support_l1`)
  ou un compte sans affectation reçoit 403 sur les cinq listes, dont
  `/incidents`.

Décisions de test (écarts consignés dans app/operator/support_lists.py) : la
garde est `require_admin_scope` (BE-120), comme sur toute route `/api/v1/admin`.
Le « rôle sans lecture des incidents » est donc un rôle sans autorité plateforme.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.billing import service
from app.billing.models import Invoice, PaymentAttempt, Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.operator.incidents import creer_incident
from app.rbac.role_assignments import AdminRoleAssignment

LISTES = ("subscriptions", "invoices", "payments", "entitlements", "incidents")


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _chemin(organisation_id: str, liste: str) -> str:
    return f"/api/v1/admin/organizations/{organisation_id}/{liste}"


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    return (await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))).json()["id"]


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=None,
            revokedAt=None,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> dict:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be131-{uuid.uuid4().hex[:12]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be131-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Compte BE-131"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})).json()
    return {"accessToken": login["accessToken"]}


async def _donnees_support(organisation_id: uuid.UUID) -> dict:
    """Un objet de chaque liste pour l'organisation ; retourne leurs identifiants par nom de liste."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be131-{uuid.uuid4().hex[:10]}", "Plan BE-131", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=organisation_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        facture = Invoice(
            subscriptionId=abonnement.id, amountCents=1000, currency="XAF", status="paid", issuedAt=maintenant,
        )
        db.add(facture)
        await db.flush()
        paiement = PaymentAttempt(
            invoiceId=facture.id, provider="test", idempotencyKey=uuid.uuid4().hex,
            amountMinor=1000, currency="XAF", status="succeeded", requestedAt=maintenant,
        )
        db.add(paiement)
        droit = SubscriptionEntitlement(
            organizationId=organisation_id, subscriptionId=abonnement.id, moduleCode="zylo_liquid",
            entitlementCode=f"be131.{uuid.uuid4().hex[:8]}", status="active", startsAt=maintenant,
            endsAt=maintenant + timedelta(days=30), sourceAttribution="offre", niveauApplication="organisation",
        )
        db.add(droit)
        incident = await creer_incident(db, severite="high", owner="equipe-be131", tenant_id=organisation_id)
        await db.commit()
        return {
            "subscriptions": abonnement.id,
            "invoices": facture.id,
            "payments": paiement.id,
            "entitlements": droit.id,
            "incidents": incident.id,
        }


async def _lignes(client: AsyncClient, utilisateur: dict, organisation_id: str, liste: str, portee: str | None = None, params: dict | None = None):
    return await client.get(_chemin(organisation_id, liste), params=params or {}, headers=_entetes(utilisateur, portee))


async def test_be131_ca1_registre_couvre_les_cinq_listes_et_chaque_liste_renvoie_l_objet(client: AsyncClient, registered_user: dict):
    from app.operator.support_lists import REGISTRE_LISTES

    assert set(REGISTRE_LISTES) == set(LISTES)
    acteur = await _moi(client, registered_user)
    await _accorder(acteur, "operateur_plateforme", "platform")
    organisation = await _organisation(client, registered_user, "Client BE-131 CA-1")
    objets = await _donnees_support(uuid.UUID(organisation["id"]))

    for liste in LISTES:
        res = await _lignes(client, registered_user, organisation["id"], liste)
        assert res.status_code == 200, f"{liste} : {res.text}"
        assert set(res.json()) == {"data", "meta"}
        assert str(objets[liste]) in [ligne["id"] for ligne in res.json()["data"]], liste


async def test_be131_ca2_filtre_hors_liste_blanche_et_periode_inversee_422(client: AsyncClient, registered_user: dict):
    acteur = await _moi(client, registered_user)
    await _accorder(acteur, "operateur_plateforme", "platform")
    organisation = await _organisation(client, registered_user, "Client BE-131 CA-2")

    res_champ = await _lignes(client, registered_user, organisation["id"], "subscriptions", params={"lifecycleStatus": "active"})
    res_periode = await _lignes(
        client, registered_user, organisation["id"], "invoices",
        params={"dateFrom": "2026-06-01T00:00:00+00:00", "dateTo": "2026-01-01T00:00:00+00:00"},
    )

    assert res_champ.status_code == 422, res_champ.text
    assert res_periode.status_code == 422, res_periode.text


async def test_be131_filtres_statut_date_et_identifiant(client: AsyncClient, registered_user: dict):
    acteur = await _moi(client, registered_user)
    await _accorder(acteur, "operateur_plateforme", "platform")
    organisation = await _organisation(client, registered_user, "Client BE-131 filtres")
    objets = await _donnees_support(uuid.UUID(organisation["id"]))
    maintenant = datetime.now(timezone.utc)
    debut = (maintenant - timedelta(days=1)).isoformat()
    fin = (maintenant + timedelta(days=1)).isoformat()

    actifs = await _lignes(client, registered_user, organisation["id"], "subscriptions", params={"status": "active"})
    expires = await _lignes(client, registered_user, organisation["id"], "subscriptions", params={"status": "expired"})
    par_id = await _lignes(client, registered_user, organisation["id"], "subscriptions", params={"id": str(objets["subscriptions"])})
    dans_periode = await _lignes(client, registered_user, organisation["id"], "invoices", params={"dateFrom": debut, "dateTo": fin})
    hors_periode = await _lignes(client, registered_user, organisation["id"], "invoices", params={"dateFrom": fin})
    incident_ouvert = await _lignes(client, registered_user, organisation["id"], "incidents", params={"status": "ouvert"})
    incident_cloture = await _lignes(client, registered_user, organisation["id"], "incidents", params={"status": "cloture"})

    assert str(objets["subscriptions"]) in [ligne["id"] for ligne in actifs.json()["data"]]
    assert expires.json()["data"] == []
    assert [ligne["id"] for ligne in par_id.json()["data"]] == [str(objets["subscriptions"])]
    assert str(objets["invoices"]) in [ligne["id"] for ligne in dans_periode.json()["data"]]
    assert hors_periode.json()["data"] == []
    assert str(objets["incidents"]) in [ligne["id"] for ligne in incident_ouvert.json()["data"]]
    assert incident_cloture.json()["data"] == []


async def test_be131_ca3_isolation_tenant_et_incidents_refuses_en_portee_tenant(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    agent_id = await _moi(client, agent)
    await _accorder(agent_id, "operateur_plateforme", "platform")
    tenant_a = await _organisation(client, agent, "Tenant A BE-131")
    proprietaire_b = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, proprietaire_b, "Tenant B BE-131")
    objets_a = await _donnees_support(uuid.UUID(tenant_a["id"]))
    objets_b = await _donnees_support(uuid.UUID(tenant_b["id"]))
    portee_a = f"tenant:{tenant_a['id']}"

    for liste in ("subscriptions", "invoices", "payments", "entitlements"):
        res_b = await _lignes(client, agent, tenant_b["id"], liste, portee=portee_a)
        assert res_b.status_code == 403, f"{liste} : {res_b.text}"
        assert str(objets_b[liste]) not in res_b.text

        res_a = await _lignes(client, agent, tenant_a["id"], liste, portee=portee_a)
        assert res_a.status_code == 200, f"{liste} : {res_a.text}"
        assert str(objets_a[liste]) in [ligne["id"] for ligne in res_a.json()["data"]]
        assert str(objets_b[liste]) not in res_a.text

    res_incidents_a = await _lignes(client, agent, tenant_a["id"], "incidents", portee=portee_a)
    assert res_incidents_a.status_code == 403, res_incidents_a.text

    res_plateforme = await _lignes(client, agent, tenant_b["id"], "subscriptions")
    assert res_plateforme.status_code == 200, res_plateforme.text
    assert str(objets_b["subscriptions"]) in [ligne["id"] for ligne in res_plateforme.json()["data"]]


async def test_be131_ca4_sans_autorite_plateforme_403_sur_toutes_les_listes(client: AsyncClient, registered_user: dict):
    agent_l1 = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent_l1), "agent_support_l1", "platform")
    sans_droit = await _nouvel_utilisateur(client)
    organisation = await _organisation(client, registered_user, "Client BE-131 CA-4")
    await _donnees_support(uuid.UUID(organisation["id"]))

    for utilisateur in (agent_l1, sans_droit):
        for liste in LISTES:
            res = await _lignes(client, utilisateur, organisation["id"], liste)
            assert res.status_code == 403, f"{liste} : {res.text}"
