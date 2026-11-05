"""BE-094 : litiges (dispute), ouverture et clôture.

Intention : prouver les critères d'acceptation de BE-094
(implementation-backend/tasks-abonnements-facturation.md, section BE-094) :
- CA-1 : un litige ouvert par évènement fournisseur passe à `opened` et met `incidentStatus`
  de l'abonnement à `disputed` (BE-091) ;
- CA-2 : un litige clôturé `lost` ne déclenche aucune écriture automatique de remboursement ;
- CA-3 : `GET` sans permission finance renvoie `FORBIDDEN` ;
- CA-4 : un litige du tenant A est invisible depuis le scope B (réponse de l'inexistant).

Ouverture et clôture passent par `POST /api/v1/billing/provider-events` (BE-083), seule entrée
des évènements fournisseur : il n'existe aucune route d'écriture publique sur les litiges.
La lecture est `GET /api/v1/billing/disputes/{disputeId}`, avec `X-Organization-Id`.
Aucun appel réseau : la signature est comparée au secret de test `FLUTTERWAVE_WEBHOOK_SECRET`.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing.models import Dispute, Invoice, PaymentAttempt, Refund, Subscription
from app.core.database import AsyncSessionLocal
from tests.test_be027_factures_lecture import ajouter_membre_sans_role, creer_organisation, utilisateur_connecte
from tests.test_be086_facture_brouillon_finalisation import _creer_facture_brouillon, _entetes

ROUTE_EVENEMENTS = "/api/v1/billing/provider-events"
SECRET = "secret-be094-test-only"


@pytest.fixture(autouse=True)
def secret_webhook(monkeypatch):
    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", SECRET)


async def _creer_paiement_reussi(client: AsyncClient, token: str, organization_id: str) -> str:
    """Crée une facture de l'organisation (abonnement inclus) puis un paiement `succeeded` rattaché."""
    facture_id = await _creer_facture_brouillon(client, token, organization_id)
    async with AsyncSessionLocal() as db:
        paiement = PaymentAttempt(
            invoiceId=uuid.UUID(facture_id), provider="fictif", mode="test",
            idempotencyKey=uuid.uuid4().hex, amountMinor=9_000, currency="XAF",
            status="succeeded", requestedAt=datetime.now(timezone.utc), providerReference=uuid.uuid4().hex,
        )
        db.add(paiement)
        await db.commit()
        return str(paiement.id)


def _evenement_litige(type_evt: str, tentative: str, statut: str, reference_litige: str) -> bytes:
    """Évènement fournisseur de litige, visant la tentative `tentative` (champ `tx_ref`)."""
    return json.dumps({
        "id": f"evt-{uuid.uuid4().hex}",
        "event": type_evt,
        "data": {"id": reference_litige, "tx_ref": tentative, "status": statut},
    }).encode()


async def _envoyer_evenement(client: AsyncClient, corps: bytes):
    return await client.post(
        ROUTE_EVENEMENTS, content=corps,
        headers={"content-type": "application/json", "verif-hash": SECRET},
    )


async def _ouvrir_litige(client: AsyncClient, tentative: str) -> str:
    """Envoie `dispute.opened` pour la tentative et renvoie la référence fournisseur du litige."""
    reference = f"dsp-{uuid.uuid4().hex}"
    reponse = await _envoyer_evenement(client, _evenement_litige("dispute.opened", tentative, "opened", reference))
    assert reponse.status_code == 200, reponse.text
    return reference


async def _litige_par_reference(reference: str) -> Dispute | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Dispute).where(Dispute.providerRef == reference))


async def _incident_de_l_abonnement(tentative: str) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Subscription.incidentStatus)
            .join(Invoice, Invoice.subscriptionId == Subscription.id)
            .join(PaymentAttempt, PaymentAttempt.invoiceId == Invoice.id)
            .where(PaymentAttempt.id == uuid.UUID(tentative))
        )


async def _nombre_de_remboursements(tentative: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(Refund).where(Refund.paymentAttemptId == uuid.UUID(tentative)))


async def test_ca1_litige_ouvert_par_evenement_fournisseur_passe_a_opened_et_incident_disputed(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """CA-1 : `dispute.opened` crée le litige en `opened` et met l'incident de l'abonnement à `disputed`."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement_reussi(client, token, org)

    reference = await _ouvrir_litige(client, paiement)

    litige = await _litige_par_reference(reference)
    assert litige is not None
    assert litige.status == "opened"
    assert litige.paymentAttemptId == uuid.UUID(paiement)
    assert litige.openedAt is not None
    assert litige.resolvedAt is None
    assert await _incident_de_l_abonnement(paiement) == "disputed"


async def test_ca2_litige_clos_lost_ne_declenche_aucun_remboursement(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """CA-2 : `dispute.resolved` avec `lost` clôt le litige ; aucun remboursement n'est créé ni modifié."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement_reussi(client, token, org)
    reference = await _ouvrir_litige(client, paiement)
    remboursements_avant = await _nombre_de_remboursements(paiement)

    reponse = await _envoyer_evenement(client, _evenement_litige("dispute.resolved", paiement, "lost", reference))

    assert reponse.status_code == 200, reponse.text
    litige = await _litige_par_reference(reference)
    assert litige.status == "lost"
    assert litige.resolvedAt is not None
    assert await _nombre_de_remboursements(paiement) == remboursements_avant == 0
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(PaymentAttempt.status).where(PaymentAttempt.id == uuid.UUID(paiement))) == "succeeded"


async def test_resolution_remet_l_incident_a_none_quand_plus_aucun_litige_n_est_ouvert(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """Clôture d'un litige unique : `incidentStatus` repasse de `disputed` à `none` (transition BE-091)."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement_reussi(client, token, org)
    reference = await _ouvrir_litige(client, paiement)

    await _envoyer_evenement(client, _evenement_litige("dispute.resolved", paiement, "won", reference))

    assert (await _litige_par_reference(reference)).status == "won"
    assert await _incident_de_l_abonnement(paiement) == "none"


async def test_ca3_lecture_sans_permission_finance_renvoie_forbidden(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """CA-3 : un membre sans permission de lecture des litiges reçoit `FORBIDDEN`."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement_reussi(client, token, org)
    reference = await _ouvrir_litige(client, paiement)
    litige = await _litige_par_reference(reference)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(org, membre["id"])

    reponse = await client.get(
        f"/api/v1/billing/disputes/{litige.id}",
        headers=_entetes(membre["accessToken"], org),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"


async def test_lecture_du_litige_par_le_proprietaire_de_l_organisation(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """Le propriétaire (permission finance par défaut) lit le litige de son organisation."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement_reussi(client, token, org)
    reference = await _ouvrir_litige(client, paiement)
    litige = await _litige_par_reference(reference)

    reponse = await client.get(f"/api/v1/billing/disputes/{litige.id}", headers=_entetes(token, org))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["id"] == str(litige.id)
    assert corps["paymentAttemptId"] == paiement
    assert corps["status"] == "opened"
    assert corps["providerRef"] == reference
    assert corps["resolvedAt"] is None


async def test_ca4_litige_d_un_autre_tenant_invisible_comme_l_inexistant(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    """CA-4 : un litige du tenant A, lu depuis le scope B, répond comme un identifiant inexistant."""
    token, org_a = registered_user["accessToken"], organization["id"]
    org_b = await creer_organisation(client, token)
    paiement = await _creer_paiement_reussi(client, token, org_a)
    reference = await _ouvrir_litige(client, paiement)
    litige = await _litige_par_reference(reference)

    hors_perimetre = await client.get(f"/api/v1/billing/disputes/{litige.id}", headers=_entetes(token, org_b))
    inexistant = await client.get(f"/api/v1/billing/disputes/{uuid.uuid4()}", headers=_entetes(token, org_b))

    assert org_a != org_b
    assert hors_perimetre.status_code == 404
    assert hors_perimetre.status_code == inexistant.status_code
    assert hors_perimetre.json()["error"]["code"] == inexistant.json()["error"]["code"] == "dispute_not_found"


async def test_aucune_route_d_ecriture_publique_sur_les_litiges(client: AsyncClient, registered_user: dict, organization: dict):
    """Ouverture et clôture sont réservées aux évènements fournisseur : POST sur un litige est refusé."""
    token, org = registered_user["accessToken"], organization["id"]

    reponse = await client.post(
        f"/api/v1/billing/disputes/{uuid.uuid4()}", json={"status": "won"}, headers=_entetes(token, org),
    )

    assert reponse.status_code in (404, 405)
