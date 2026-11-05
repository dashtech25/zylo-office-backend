"""BE-087 : avoir et correction d'une facture finalisée.

Intention : prouver les critères d'acceptation de BE-087
(implementation-backend/tasks-abonnements-facturation.md, section BE-087) :
- CA-1 : un avoir est toujours lié à une facture finalisée ; la facture d'origine
  n'est pas modifiée (ligne `invoice` identique avant et après, et refus d'un avoir
  sur un brouillon par INVALID_TRANSITION) ;
- CA-2 : un avoir sans motif est refusé (APPROVAL_REQUIRED), rien n'est écrit ;
- CA-3 : sans approbation requise (approbateur absent, identique à l'acteur ou non
  membre), APPROVAL_REQUIRED ; sans permission finance, FORBIDDEN ;
- CA-4 : un avoir ne peut viser qu'une facture du même scope : une facture d'une autre
  organisation répond 404 invoice_not_found, comme une facture inexistante.

Route testée : `POST /api/v1/billing/invoices/{invoiceId}/credit-notes`.
Corps : `{"amount": int, "reason": str, "approverId": uuid | null}`.
L'organisation courante vient de l'en-tête `X-Organization-Id`.

Les montants attendus sont des constantes écrites à la main, jamais recalculées par le code testé.
Le montage réutilise les helpers de BE-086 (brouillon, finalisation) et de BE-027 (membres).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.billing.models import CreditNote, Invoice
from app.core.database import AsyncSessionLocal
from tests.test_be027_factures_lecture import ajouter_membre_sans_role, creer_organisation, utilisateur_connecte
from tests.test_be086_facture_brouillon_finalisation import (
    MOTIF,
    TOTAL_ATTENDU,
    _creer_facture_brouillon,
    _entetes,
    _statut_base,
)

# Montant de l'avoir, en unités mineures : inférieur au total de la facture (11 925).
MONTANT_AVOIR = 4_000
MOTIF_AVOIR = "Correction de test BE-087"


async def _facture_finalisee(client: AsyncClient, token: str, organization_id: str) -> str:
    """Crée un brouillon BE-086 puis le finalise par la route de BE-086 ; renvoie son identifiant."""
    facture_id = await _creer_facture_brouillon(client, token, organization_id)
    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/finalize", json={"reason": MOTIF}, headers=_entetes(token, organization_id),
    )
    assert reponse.status_code == 200, reponse.text
    return facture_id


async def _nombre_d_avoirs(invoice_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(CreditNote).where(CreditNote.invoiceId == uuid.UUID(invoice_id)))


async def _approbateur_membre(client: AsyncClient, organization_id: str) -> str:
    """Un second utilisateur rattaché à l'organisation, distinct de l'acteur ; renvoie son identifiant."""
    approbateur = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(organization_id, approbateur["id"])
    return approbateur["id"]


def _corps(*, approbateur_id: str | None, motif: str = MOTIF_AVOIR, montant: int = MONTANT_AVOIR) -> dict:
    return {"amount": montant, "reason": motif, "approverId": approbateur_id}


async def test_avoir_sur_facture_finalisee_est_lie_et_ne_modifie_pas_la_facture(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)
    avant = await _statut_base(facture_id)
    approbateur = await _approbateur_membre(client, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=approbateur), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["invoiceId"] == facture_id
    assert corps["amount"] == MONTANT_AVOIR
    assert corps["currency"] == "XAF"
    assert corps["reason"] == MOTIF_AVOIR
    assert corps["status"] == "issued"
    assert await _nombre_d_avoirs(facture_id) == 1
    apres = await _statut_base(facture_id)
    assert (apres.status, apres.total, apres.version, apres.taxSnapshot) == (avant.status, avant.total, avant.version, avant.taxSnapshot)
    assert apres.total == TOTAL_ATTENDU
    assert apres.status == "finalized"


async def test_avoir_ecrit_une_entree_d_audit_avec_motif_et_approbateur(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)
    approbateur = await _approbateur_membre(client, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=approbateur), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 201, reponse.text
    async with AsyncSessionLocal() as db:
        entree = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "billing.credit_note.issue", AuditEvent.entity_id == uuid.UUID(reponse.json()["id"]))
        )
    assert entree is not None
    assert entree.reason == MOTIF_AVOIR
    assert entree.approval_id == approbateur


async def test_avoir_sans_motif_renvoie_approval_required_sans_effet(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)
    approbateur = await _approbateur_membre(client, organisation_id)

    for motif in ("", "   "):
        reponse = await client.post(
            f"/api/v1/billing/invoices/{facture_id}/credit-notes",
            json=_corps(approbateur_id=approbateur, motif=motif), headers=_entetes(token, organisation_id),
        )
        assert reponse.status_code == 422, reponse.text
        assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert await _nombre_d_avoirs(facture_id) == 0


async def test_avoir_sans_approbateur_renvoie_approval_required_sans_effet(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=None), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert await _nombre_d_avoirs(facture_id) == 0


async def test_approbateur_identique_a_l_acteur_renvoie_approval_required(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=registered_user["id"]), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert await _nombre_d_avoirs(facture_id) == 0


async def test_approbateur_non_membre_de_l_organisation_renvoie_approval_required(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    facture_id = await _facture_finalisee(client, token, organisation_id)
    hors_organisation = await utilisateur_connecte(client)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=hors_organisation["id"]), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert await _nombre_d_avoirs(facture_id) == 0


async def test_membre_sans_permission_finance_recoit_forbidden(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    facture_id = await _facture_finalisee(client, registered_user["accessToken"], organisation_id)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(organisation_id, membre["id"])
    approbateur = await _approbateur_membre(client, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_id}/credit-notes",
        json=_corps(approbateur_id=approbateur), headers=_entetes(membre["accessToken"], organisation_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert await _nombre_d_avoirs(facture_id) == 0


async def test_avoir_sur_facture_brouillon_renvoie_invalid_transition(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_id = organization["id"]
    token = registered_user["accessToken"]
    brouillon_id = await _creer_facture_brouillon(client, token, organisation_id)
    approbateur = await _approbateur_membre(client, organisation_id)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{brouillon_id}/credit-notes",
        json=_corps(approbateur_id=approbateur), headers=_entetes(token, organisation_id),
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await _nombre_d_avoirs(brouillon_id) == 0


async def test_avoir_sur_facture_d_une_autre_organisation_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    token = registered_user["accessToken"]
    o1 = organization["id"]
    o2 = await creer_organisation(client, token)
    facture_o2 = await _facture_finalisee(client, token, o2)
    approbateur = await _approbateur_membre(client, o1)

    reponse = await client.post(
        f"/api/v1/billing/invoices/{facture_o2}/credit-notes",
        json=_corps(approbateur_id=approbateur), headers=_entetes(token, o1),
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "invoice_not_found"
    assert await _nombre_d_avoirs(facture_o2) == 0
