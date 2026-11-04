"""BE-086 : facture brouillon et finalisation.

Intention : prouver les critères d'acceptation de BE-086
(implementation-backend/tasks-abonnements-facturation.md, section BE-086) :
- CA-1 : une facture finalisée est append-only (INVALID_TRANSITION côté service,
  refus de la base pour une écriture directe) ;
- CA-2 : finaliser sans devise ni taxe configurées renvoie CURRENCY_NOT_CONFIGURED
  ou TAX_NOT_CONFIGURED, et aucune facture n'est finalisée ;
- CA-3 : finaliser sans permission finance renvoie FORBIDDEN ;
- CA-4 : GET d'une facture hors scope renvoie la réponse de l'inexistant (404) ;
- CA-5 : la finalisation écrit une entrée d'audit et publie `InvoiceFinalized`.

Routes testées : `POST /api/v1/billing/invoices/{invoiceId}/finalize` et
`GET /api/v1/billing/invoices/{invoiceId}`. L'organisation courante vient de
l'en-tête `X-Organization-Id`.

Montage volontairement minimal : la création d'un brouillon n'est pas livrée par
BE-086 (les lignes de facture et la numérotation sont NON DÉFINI, QE-FAC-04 et
QE-FAC-15). Le brouillon est donc obtenu depuis une facture émise par la route
existante, puis son statut est posé en base par une seule écriture. Les montants
attendus sont des constantes écrites à la main, jamais recalculées par le code testé.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.audit.models import AuditEvent
from app.billing import service
from app.billing.models import Invoice
from app.billing.pricing.resolution import definir_regle_prix
from app.core.database import AsyncSessionLocal
from app.shared import events as bus
from tests.test_be027_factures_lecture import ajouter_membre_sans_role, creer_organisation, utilisateur_connecte

# Scénario de tarification utilisé pour la facture (valeur provisoire, QE-FAC-10).
SCENARIO_FACTURE = "facture"
# Montant HT 10 000 unités mineures, taxe 19,25 % (1925 points de base) : total attendu 11 925.
MONTANT_HT = 10_000
TAUX_TAXE_BPS = 1925
TOTAL_ATTENDU = 11_925
MOTIF = "Finalisation de test BE-086"


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _creer_facture_brouillon(client: AsyncClient, token: str, organization_id: str, *, devise: str | None = "XAF", taux: int | None = TAUX_TAXE_BPS) -> str:
    """Crée un abonnement, une facture émise, configure la règle de prix, puis pose le statut `draft`.

    `devise` et `taux` configurent la règle de prix (None = non configuré). Renvoie l'identifiant de la facture.
    """
    headers = _entetes(token, organization_id)
    code = f"plan-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-086", MONTANT_HT, "XAF", 30)
        await definir_regle_prix(
            db, organization_id=uuid.UUID(organization_id), object_code=plan.code, scenario=SCENARIO_FACTURE,
            amount_minor=MONTANT_HT, currency=devise, tax_rate_bps=taux,
        )
    abonnement = await client.post(f"/api/v1/billing/organizations/{organization_id}/subscriptions", json={"planCode": code}, headers=headers)
    assert abonnement.status_code == 201, abonnement.text
    facture = await client.post(
        f"/api/v1/billing/organizations/{organization_id}/invoices",
        json={"subscriptionId": abonnement.json()["id"]},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert facture.status_code == 201, facture.text
    invoice_id = facture.json()["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(update(Invoice).where(Invoice.id == uuid.UUID(invoice_id)).values(status="draft"))
        await db.commit()
    return invoice_id


async def _statut_base(invoice_id: str) -> Invoice:
    async with AsyncSessionLocal() as db:
        return await db.get(Invoice, uuid.UUID(invoice_id), populate_existing=True)


async def test_finalisation_passe_la_facture_a_finalized_avec_total_calcule(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)

    reponse = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["status"] == "finalized"
    assert corps["total"] == TOTAL_ATTENDU
    assert corps["finalizedAt"] is not None
    facture = await _statut_base(facture_id)
    assert facture.status == "finalized"
    assert facture.total == TOTAL_ATTENDU
    assert facture.taxSnapshot["taxRateBps"] == TAUX_TAXE_BPS


async def test_finaliser_sans_devise_renvoie_currency_not_configured_sans_effet(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id, devise=None)

    reponse = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["error"]["code"] == "CURRENCY_NOT_CONFIGURED"
    facture = await _statut_base(facture_id)
    assert facture.status == "draft"
    assert facture.finalizedAt is None


async def test_finaliser_sans_taxe_renvoie_tax_not_configured_sans_effet(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id, taux=None)

    reponse = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["error"]["code"] == "TAX_NOT_CONFIGURED"
    facture = await _statut_base(facture_id)
    assert facture.status == "draft"


async def test_membre_sans_permission_finance_recoit_forbidden(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(organisation_id, membre["id"])

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF},
        headers=_entetes(membre["accessToken"], organisation_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert (await _statut_base(facture_id)).status == "draft"


async def test_facture_finalisee_ne_se_finalise_pas_deux_fois(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)
    premiere = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)
    assert premiere.status_code == 200, premiere.text

    seconde = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)

    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_base_refuse_la_modification_d_une_facture_finalisee(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)
    await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text('UPDATE invoice SET "total" = 1 WHERE id = :id'), {"id": uuid.UUID(facture_id)})
            await db.commit()
    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM invoice WHERE id = :id"), {"id": uuid.UUID(facture_id)})
            await db.commit()
    assert (await _statut_base(facture_id)).total == TOTAL_ATTENDU


async def test_get_facture_d_un_autre_tenant_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_a = organization["id"]
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_a)
    organisation_b = await creer_organisation(client, registered_user["accessToken"])

    reponse_b = await client.get(f"/api/v1/billing/invoices/{facture_id}", headers=_entetes(registered_user["accessToken"], organisation_b))
    reponse_inexistante = await client.get(
        f"/api/v1/billing/invoices/{uuid.uuid4()}", headers=_entetes(registered_user["accessToken"], organisation_b),
    )

    assert reponse_b.status_code == 404
    assert reponse_inexistante.status_code == 404
    # Même réponse que pour une facture absente, à l'identifiant de requête près.
    corps_b = {k: v for k, v in reponse_b.json()["error"].items()}
    corps_inexistante = {k: v for k, v in reponse_inexistante.json()["error"].items()}
    assert corps_b == corps_inexistante


async def test_get_facture_du_tenant_courant_renvoie_son_statut(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)

    reponse = await client.get(f"/api/v1/billing/invoices/{facture_id}", headers=_entetes(registered_user["accessToken"], organisation_id))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["id"] == facture_id
    assert reponse.json()["status"] == "draft"


async def test_finalisation_ecrit_audit_et_publie_invoice_finalized(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    headers = _entetes(registered_user["accessToken"], organisation_id)
    facture_id = await _creer_facture_brouillon(client, registered_user["accessToken"], organisation_id)
    recus: list[dict] = []

    async def gestionnaire(**payload) -> None:
        recus.append(payload)

    bus.subscribe("InvoiceFinalized", gestionnaire)
    try:
        reponse = await client.post(f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=headers)
    finally:
        bus._handlers["InvoiceFinalized"].remove(gestionnaire)

    assert reponse.status_code == 200, reponse.text
    async with AsyncSessionLocal() as db:
        entrees = (await db.scalars(select(AuditEvent).where(
            AuditEvent.action == "billing.invoice.finalize", AuditEvent.entityId == uuid.UUID(facture_id),
        ))).all()
    assert len(entrees) == 1
    assert entrees[0].reason == MOTIF
    assert len(recus) == 1
    assert str(recus[0].get("invoice_id", recus[0].get("invoiceId"))) == facture_id
