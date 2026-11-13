"""BE-130 : vue synthèse des états de compte (console de support, lecture).

Tests écrits d'après la définition `### BE-130` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route : `GET /api/v1/admin/organizations/{organization_id}/summary`, en portée
`tenant:<organization_id>` (BE-120 : la portée plateforme ne couvre jamais le
contenu d'un tenant, elle reçoit 403).

Couverture :
- CA-1 : la réponse contient les sept sections (offre, abonnement, paiement,
  factures, droits, incidents, échéances), chacune renseignée ou marquée N/A
  explicite (test de schéma) ;
- CA-2 (refus de droit) : agent L1 : les sections paiement et factures sont
  masquées ; un rôle finance les voit ;
- CA-3 (isolation tenant) : un compte lié au tenant A demandant la synthèse du
  tenant B reçoit 403 ; un compte sans affectation au tenant reçoit 403 ;
- CA-4 : aucun champ santé ou réputation n'apparaît dans la réponse.

Décisions de test : les comptes de support portent `operateur_plateforme`
(autorité de BE-120, seule voie d'accès aux routes `/api/v1/admin`) et le rôle
de support testé (`agent_support_l1`, `finance_support`, ...).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.billing import service
from app.billing.models import Invoice, PaymentAttempt, Subscription
from app.core.database import AsyncSessionLocal, engine
from app.operator.incidents_models import Incident
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_SYNTHESE = "/api/v1/admin/organizations/{organization_id}/summary"
SECTIONS_ATTENDUES = {"offre", "abonnement", "paiement", "factures", "droits", "incidents", "echeances"}
MOTS_INTERDITS = ("sante", "santé", "reputation", "réputation", "health", "score")


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après.

    Le module `zylo_liquid` est semé comme le fait la fixture `client`
    (plan.moduleCode)."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    return (await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))).json()["id"]


async def _accorder(actor_id: str, role_code: str, scope: str = "platform") -> None:
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


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be130-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Compte BE-130"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})).json()
    return {"accessToken": login["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> dict:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-130", "slug": f"be130-{uuid.uuid4().hex[:12]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _abonnement_avec_factures(organization_id: str) -> uuid.UUID:
    """Abonnement du tenant, une facture en attente et une tentative de paiement échouée."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be130-{uuid.uuid4().hex[:8]}", "Plan BE-130", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=uuid.UUID(organization_id),
            planId=plan.id,
            status="trial",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=uuid.UUID(organization_id),
            lifecycleStatus="trialing",
            financialStatus="none",
            incidentStatus="none",
        )
        db.add(abonnement)
        await db.flush()
        facture = Invoice(
            subscriptionId=abonnement.id,
            amountCents=1000,
            currency="XAF",
            status="pending",
            issuedAt=maintenant,
        )
        db.add(facture)
        await db.flush()
        db.add(PaymentAttempt(
            invoiceId=facture.id,
            provider="test",
            idempotencyKey=f"be130-{uuid.uuid4().hex}",
            amountMinor=1000,
            currency="XAF",
            status="failed",
            requestedAt=maintenant,
        ))
        await db.commit()
        return abonnement.id


async def _incident_du_tenant(organization_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(Incident(
            severity="high",
            owner="support",
            state="ouvert",
            occurredAt=datetime.now(timezone.utc),
            tenantId=uuid.UUID(organization_id),
        ))
        await db.commit()


async def test_be130_ca1_schema_sept_sections_renseignees_ou_n_a(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme")
    organisation = await _organisation(client, agent)
    await _abonnement_avec_factures(organisation["id"])

    res = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(agent, f"tenant:{organisation['id']}"),
    )

    assert res.status_code == 200, res.text
    donnees = res.json()["data"]
    assert set(donnees.keys()) >= SECTIONS_ATTENDUES
    for nom in SECTIONS_ATTENDUES:
        section = donnees[nom]
        assert isinstance(section, dict) and section, nom
    assert donnees["abonnement"]["lifecycleStatus"] == "trialing"
    assert donnees["offre"]["statut"] == "N/A"


async def test_be130_ca2_agent_l1_voit_factures_et_paiement_masques(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    agent_id = await _moi(client, agent)
    await _accorder(agent_id, "operateur_plateforme")
    await _accorder(agent_id, "agent_support_l1")
    organisation = await _organisation(client, agent)
    await _abonnement_avec_factures(organisation["id"])

    res = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(agent, f"tenant:{organisation['id']}"),
    )

    assert res.status_code == 200, res.text
    donnees = res.json()["data"]
    assert donnees["factures"] == {"statut": "masque"}
    assert donnees["paiement"] == {"statut": "masque"}
    assert "pending" not in res.text
    assert "failed" not in res.text


async def test_be130_ca2_role_finance_voit_les_donnees_financieres(client: AsyncClient, registered_user: dict):
    finance = await _nouvel_utilisateur(client)
    finance_id = await _moi(client, finance)
    await _accorder(finance_id, "operateur_plateforme")
    await _accorder(finance_id, "finance_support")
    organisation = await _organisation(client, finance)
    await _abonnement_avec_factures(organisation["id"])

    res = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(finance, f"tenant:{organisation['id']}"),
    )

    assert res.status_code == 200, res.text
    donnees = res.json()["data"]
    assert donnees["factures"]["nombre"] == 1
    assert donnees["paiement"]["derniereTentative"] == "failed"


async def test_be130_ca3_tenant_b_refuse_a_un_compte_lie_au_tenant_a(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme")
    tenant_a = await _organisation(client, agent)
    proprietaire_b = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, proprietaire_b)
    await _abonnement_avec_factures(tenant_b["id"])

    res_scope_a_cible_b = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=tenant_b["id"]),
        headers=_entetes(agent, f"tenant:{tenant_a['id']}"),
    )
    res_scope_b = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=tenant_b["id"]),
        headers=_entetes(agent, f"tenant:{tenant_b['id']}"),
    )

    assert res_scope_a_cible_b.status_code == 403
    assert res_scope_b.status_code == 403
    assert tenant_b["id"] not in res_scope_a_cible_b.text
    assert tenant_b["id"] not in res_scope_b.text


async def test_be130_ca3_sans_affectation_au_tenant_ou_sans_autorite_403(client: AsyncClient, registered_user: dict):
    proprietaire = await _nouvel_utilisateur(client)
    organisation = await _organisation(client, proprietaire)
    sans_autorite = await _nouvel_utilisateur(client)

    res_sans_autorite = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(proprietaire, f"tenant:{organisation['id']}"),
    )
    res_inconnu = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(sans_autorite, f"tenant:{organisation['id']}"),
    )

    assert res_sans_autorite.status_code == 403
    assert res_inconnu.status_code == 403


async def test_be130_portee_plateforme_ne_couvre_pas_le_contenu_tenant(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme")
    organisation = await _organisation(client, agent)

    res = await client.get(CHEMIN_SYNTHESE.format(organization_id=organisation["id"]), headers=_entetes(agent))

    assert res.status_code == 403


async def test_be130_ca4_aucun_champ_sante_ou_reputation(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme")
    await _accorder(await _moi(client, agent), "finance_support")
    organisation = await _organisation(client, agent)
    await _abonnement_avec_factures(organisation["id"])
    await _incident_du_tenant(organisation["id"])

    res = await client.get(
        CHEMIN_SYNTHESE.format(organization_id=organisation["id"]),
        headers=_entetes(agent, f"tenant:{organisation['id']}"),
    )

    assert res.status_code == 200, res.text
    assert set(res.json()["data"].keys()) == SECTIONS_ATTENDUES | {"organizationId"}
    texte = res.text.lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, mot
    assert res.json()["data"]["incidents"]["nombre"] == 1
