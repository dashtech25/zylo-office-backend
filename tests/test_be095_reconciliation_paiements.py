"""BE-095 : réconciliation des paiements et résultats incertains.

Intention : prouver les critères d'acceptation de BE-095
(implementation-backend/tasks-abonnements-facturation.md, section BE-095) :
- CA-1 : une tentative `unknown` est recherchée auprès du fournisseur sous la même référence
  avant toute nouvelle capture (test de non-double-débit : aucun appel `charge`) ;
- CA-2 : un écart détecté crée `ReconciliationDifferenceDetected` (outbox) sans correction
  automatique de la tentative ;
- CA-3 : sans permission de réconciliation, `FORBIDDEN` ; rien n'est écrit, aucun appel fournisseur ;
- CA-4 : une réconciliation ne porte que sur le tenant demandé (en-tête `X-Organization-Id`).

Route testée : `POST /api/v1/billing/reconciliations`. Corps : `{"scope": "tenant", "periodKey": str | null}`.
Le fournisseur est remplacé par un double (`FournisseurReconciliationFictif`) via
`app.dependency_overrides` : il enregistre chaque appel `rechercher` et `charge`, sans réseau.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing.models import PaymentAttempt, ReconciliationDifference, ReconciliationRun
from app.billing.payment_provider import PaymentProvider
from app.billing.reconciliation.router import obtenir_fournisseur_reconciliation
from app.core.database import AsyncSessionLocal
from app.evenements.models import OutboxEvenement
from app.main import app
from tests.test_be027_factures_lecture import ajouter_membre_sans_role, creer_organisation, utilisateur_connecte
from tests.test_be086_facture_brouillon_finalisation import _creer_facture_brouillon, _entetes

MONTANT_TENTATIVE = 5_000
TYPE_EVENEMENT_ECART = "Billing.ReconciliationDifferenceDetected"


class FournisseurReconciliationFictif(PaymentProvider):
    """Double du fournisseur : enregistre les appels, renvoie la réponse fixée par le test.

    `reponse` est la réponse de `rechercher` : True = le fournisseur a un débit confirmé sous la
    référence, False = aucune trace. `charge` ne doit JAMAIS être appelé par la réconciliation.
    """

    provider = "fictif"
    mode = "test"

    def __init__(self, reponse: bool = False):
        self.reponse = reponse
        self.recherches: list[str] = []
        self.charges: list[str] = []

    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        self.charges.append(reference)
        raise AssertionError("La réconciliation ne doit jamais initier une capture.")

    async def rechercher(self, reference: str) -> bool:
        self.recherches.append(reference)
        return self.reponse


@pytest.fixture
def fournisseur_fictif():
    """Installe le double pour la route de réconciliation et le retire après le test."""
    fournisseur = FournisseurReconciliationFictif()
    app.dependency_overrides[obtenir_fournisseur_reconciliation] = lambda: fournisseur
    yield fournisseur
    app.dependency_overrides.pop(obtenir_fournisseur_reconciliation, None)


async def _creer_tentative_inconnue(client: AsyncClient, token: str, organization_id: str) -> str:
    """Crée une facture de l'organisation puis une tentative de paiement au statut `unknown`."""
    facture_id = await _creer_facture_brouillon(client, token, organization_id)
    async with AsyncSessionLocal() as db:
        tentative = PaymentAttempt(
            invoiceId=uuid.UUID(facture_id), provider="fictif", mode="test",
            idempotencyKey=uuid.uuid4().hex, amountMinor=MONTANT_TENTATIVE, currency="XAF",
            status="unknown", requestedAt=datetime.now(timezone.utc),
        )
        db.add(tentative)
        await db.commit()
        return str(tentative.id)


async def _nombre_de_tentatives(facture_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(select(PaymentAttempt).where(PaymentAttempt.invoiceId == uuid.UUID(facture_id)))).all())


async def _statut_tentative(tentative_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(PaymentAttempt, uuid.UUID(tentative_id), populate_existing=True)).status


async def _ecarts_de_la_tentative(tentative_id: str) -> list[ReconciliationDifference]:
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(
            select(ReconciliationDifference).where(ReconciliationDifference.paymentAttemptId == uuid.UUID(tentative_id))
        )).all())


async def _nombre_de_runs(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(ReconciliationRun).where(ReconciliationRun.organizationId == uuid.UUID(organization_id))
        )).scalar_one()


async def _nombre_evenements_ecart(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(OutboxEvenement).where(
                OutboxEvenement.eventType == TYPE_EVENEMENT_ECART, OutboxEvenement.tenantId == uuid.UUID(organization_id),
            )
        )).scalar_one()


async def test_ca1_tentative_unknown_recherchee_avant_toute_capture(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-1 : la tentative `unknown` est recherchée sous sa référence ; aucun appel `charge` ; rien de créé."""
    token, org = registered_user["accessToken"], organization["id"]
    tentative = await _creer_tentative_inconnue(client, token, org)

    reponse = await client.post(
        "/api/v1/billing/reconciliations", json={"scope": "tenant", "periodKey": "2026-11"}, headers=_entetes(token, org),
    )

    assert reponse.status_code == 201, reponse.text
    assert fournisseur_fictif.recherches == [tentative], "la recherche se fait sous la référence de la tentative"
    assert fournisseur_fictif.charges == [], "aucune nouvelle capture (non-double-débit)"
    assert await _statut_tentative(tentative) == "unknown"


async def test_ca2_ecart_detecte_sans_correction_automatique(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-2 : le fournisseur confirme un débit que Zylo ignore : un écart est créé, un évènement est
    écrit dans l'outbox, et la tentative reste `unknown` (aucune correction automatique)."""
    token, org = registered_user["accessToken"], organization["id"]
    tentative = await _creer_tentative_inconnue(client, token, org)
    fournisseur_fictif.reponse = True

    reponse = await client.post(
        "/api/v1/billing/reconciliations", json={"scope": "tenant", "periodKey": None}, headers=_entetes(token, org),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["differenceCount"] == 1
    assert corps["scope"] == "tenant"
    ecarts = await _ecarts_de_la_tentative(tentative)
    assert len(ecarts) == 1
    assert ecarts[0].status == "detected"
    assert str(ecarts[0].runId) == corps["id"]
    assert await _statut_tentative(tentative) == "unknown", "aucune correction automatique"
    assert await _nombre_evenements_ecart(org) == 1


async def test_ca3_sans_permission_reconciliation_renvoie_forbidden(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-3 : un membre sans permission reçoit FORBIDDEN ; aucun run, aucun appel fournisseur."""
    token, org = registered_user["accessToken"], organization["id"]
    await _creer_tentative_inconnue(client, token, org)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(org, membre["id"])

    reponse = await client.post(
        "/api/v1/billing/reconciliations", json={"scope": "tenant", "periodKey": None}, headers=_entetes(membre["accessToken"], org),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert fournisseur_fictif.recherches == []
    assert await _nombre_de_runs(org) == 0


async def test_ca4_reconciliation_limitee_au_tenant_demande(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-4 : la tentative `unknown` d'un autre tenant n'est ni recherchée ni comptée dans l'écart."""
    token, org = registered_user["accessToken"], organization["id"]
    autre_tenant = await creer_organisation(client, token)
    tentative_propre = await _creer_tentative_inconnue(client, token, org)
    tentative_autre = await _creer_tentative_inconnue(client, token, autre_tenant)
    fournisseur_fictif.reponse = True

    reponse = await client.post(
        "/api/v1/billing/reconciliations", json={"scope": "tenant", "periodKey": None}, headers=_entetes(token, org),
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["differenceCount"] == 1
    assert fournisseur_fictif.recherches == [tentative_propre]
    assert tentative_autre not in fournisseur_fictif.recherches
    assert await _ecarts_de_la_tentative(tentative_autre) == []
