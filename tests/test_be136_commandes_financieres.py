"""BE-136 : préparation d'opérations financières, sans exécution PSP.

Tests écrits d'après la définition `### BE-136` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route visée (décision : préfixe `/api/v1/admin`) :
- `POST /api/v1/admin/invoices/{invoice_id}/finance-commands` : crée une intention
  de classe `facturation.operation` sur la facture (201, ou 200 au rejeu identique).

Couverture :
- CA-1 (refus de droit) : un agent L1 sur le tenant de la facture reçoit 403 ;
- CA-2 : un champ de carte (numéro, CVV) est rejeté en 422 et n'est pas journalisé
  (aucune intention créée, aucune valeur renvoyée dans la réponse d'erreur) ;
- CA-3 : la préparation n'émet aucun appel au PSP (client simulé, zéro appel) ;
- CA-4 (isolation tenant) : un responsable finance du tenant A ne prépare pas une
  facture du tenant B : 403 ;
- CA-5 : un refus par absence d'autorité ouvre un cas d'escalade finance
  (test de présence d'une ligne `intervention_case`).

Hypothèses consignées (voir le rapport de la tâche) :
- l'autorité finance (PH-10) est portée par le rôle `finance_support` sur la portée
  du tenant de la facture ; la permission `admin.finance.prepare` reste NON DÉFINIE ;
- le tenant d'une facture est celui de son abonnement (`beneficiaryTenantId`).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import Invoice, Plan, Subscription
from app.billing.payment_provider import FlutterwaveTestProvider
from app.core.database import AsyncSessionLocal
from app.operator.cases import InterventionCase
from app.operator.commands import AdminCommand
from app.rbac.role_assignments import AdminRoleAssignment

MOT_DE_PASSE = "TestPassword123!"
CLASSE = "facturation.operation"
ROLE_FINANCE = "finance_support"
ROLE_L1 = "agent_support_l1"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _chemin(invoice_id: str) -> str:
    return f"/api/v1/admin/invoices/{invoice_id}/finance-commands"


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be136-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-136"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


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


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"tenant-be136-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _facture(tenant_id: str) -> str:
    """Une facture minimale rattachée à un abonnement du tenant ; renvoie son id.

    Fixture volontairement réduite : un plan, sa version, un abonnement, une facture.
    """
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be136-{uuid.uuid4().hex[:10]}", "Plan BE-136", 0, "XAF", 30,
        )
        version = await service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=uuid.UUID(tenant_id), beneficiaryTenantId=uuid.UUID(tenant_id),
            planId=plan.id, planVersionId=version.id, status="active",
            startDate=now, endDate=now + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        facture = Invoice(
            subscriptionId=abonnement.id, amountCents=1000, currency="XAF", status="pending", issuedAt=now,
        )
        db.add(facture)
        await db.commit()
        return str(facture.id)


def _corps(**surcharge) -> dict:
    corps = {"reasonTicket": "INC-136", "idempotencyKey": uuid.uuid4().hex}
    corps.update(surcharge)
    return corps


async def _nombre_commandes(acteur_id: str) -> int:
    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(AdminCommand).where(AdminCommand.actorId == uuid.UUID(acteur_id))
        return (await db.execute(stmt)).scalar_one()


async def _nombre_escalades(acteur_id: str) -> int:
    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(InterventionCase).where(
            InterventionCase.openedBy == uuid.UUID(acteur_id),
            InterventionCase.qualification.like("Escalade finance%"),
        )
        return (await db.execute(stmt)).scalar_one()


@pytest.fixture
def psp_simule(monkeypatch):
    """Client PSP simulé : chaque méthode d'appel au prestataire est espionnée."""
    appels: list[str] = []

    def espion(nom: str):
        async def _appel(self, *args, **kwargs):
            appels.append(nom)
            return True
        return _appel

    for nom in ("charge", "rembourser", "create_checkout"):
        monkeypatch.setattr(FlutterwaveTestProvider, nom, espion(nom))
    return appels


async def test_be136_ca1_agent_l1_prepare_une_operation_financiere_renvoie_403(
    client: AsyncClient, psp_simule,
):
    proprietaire = await _nouvel_utilisateur(client)
    agent = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, proprietaire, "Tenant A BE-136")
    await _accorder(agent["id"], ROLE_L1, f"tenant:{tenant}")
    facture = await _facture(tenant)

    reponse = await client.post(_chemin(facture), json=_corps(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_commandes(agent["id"]) == 0
    assert psp_simule == []


async def test_be136_ca2_champ_de_carte_est_rejete_en_422_et_non_journalise(
    client: AsyncClient, psp_simule,
):
    proprietaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, proprietaire, "Tenant CA2 BE-136")
    await _accorder(proprietaire["id"], ROLE_FINANCE, f"tenant:{tenant}")
    facture = await _facture(tenant)
    numero_carte = "4242424242424242"

    reponse = await client.post(
        _chemin(facture),
        json=_corps(numeroCarte=numero_carte, cvv="123"),
        headers=_entetes(proprietaire),
    )

    assert reponse.status_code == 422, reponse.text
    assert numero_carte not in reponse.text
    assert await _nombre_commandes(proprietaire["id"]) == 0
    assert psp_simule == []


async def test_be136_ca3_preparation_n_appelle_aucun_psp(client: AsyncClient, psp_simule):
    proprietaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, proprietaire, "Tenant CA3 BE-136")
    await _accorder(proprietaire["id"], ROLE_FINANCE, f"tenant:{tenant}")
    facture = await _facture(tenant)

    reponse = await client.post(_chemin(facture), json=_corps(), headers=_entetes(proprietaire))

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["status"] == "intention"
    assert reponse.json()["commandType"] == CLASSE
    assert psp_simule == [], "aucun appel PSP ne doit être émis par la préparation"


async def test_be136_ca4_finance_du_tenant_a_ne_prepare_pas_la_facture_du_tenant_b(
    client: AsyncClient, psp_simule,
):
    proprietaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, proprietaire, "Tenant A CA4 BE-136")
    tenant_b = await _organisation(client, proprietaire, "Tenant B CA4 BE-136")
    finance = await _nouvel_utilisateur(client)
    await _accorder(finance["id"], ROLE_FINANCE, f"tenant:{tenant_a}")
    facture_b = await _facture(tenant_b)

    reponse = await client.post(_chemin(facture_b), json=_corps(), headers=_entetes(finance))

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_commandes(finance["id"]) == 0
    assert psp_simule == []


async def test_be136_ca5_refus_par_absence_d_autorite_ouvre_une_escalade_finance(
    client: AsyncClient, psp_simule,
):
    proprietaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, proprietaire, "Tenant CA5 BE-136")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L1, f"tenant:{tenant}")
    facture = await _facture(tenant)
    avant = await _nombre_escalades(agent["id"])

    reponse = await client.post(_chemin(facture), json=_corps(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_escalades(agent["id"]) == avant + 1, "un cas d'escalade finance doit être ouvert"
