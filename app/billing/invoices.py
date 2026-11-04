"""Facture : brouillon et finalisation (BE-086).

Cycle de vie porté ici : `draft` -> `finalized`. Les états suivants (`open`,
`partially_paid`, `paid`) relèvent des paiements et ne sont pas écrits par ce module.

Règles tenues par `finaliser_facture` :

1. Motif obligatoire (geste sensible de BE-073) : `APPROVAL_REQUIRED` sinon, rien n'est écrit.
2. Verrou de ligne (`SELECT ... FOR UPDATE`) : deux finalisations concurrentes ne peuvent
   pas passer toutes les deux. Une facture hors du périmètre de l'organisation est
   répondue comme inexistante (404 `invoice_not_found`, pas de fuite d'existence).
3. Seul un brouillon se finalise : toute autre valeur renvoie `INVALID_TRANSITION` (409).
4. Prix, devise et taxe viennent de la règle de tarification (BE-078, `resoudre_prix`) :
   absence de règle, de devise ou de taux renvoie `PRICE_NOT_CONFIGURED`,
   `CURRENCY_NOT_CONFIGURED` ou `TAX_NOT_CONFIGURED` avant toute écriture (CA-2).
5. Le total est calculé une seule fois, en entiers : taxe = montant x taux (points de base)
   / 10 000, arrondie à l'entier le plus proche (demi vers le haut). Le résultat est figé dans
   `total` et `taxSnapshot` ; les lectures ultérieures ne recalculent rien.
6. Une seule transaction écrit la facture, l'entrée d'audit `billing.invoice.finalize`
   (`app/billing/audit.py`) et commit. L'événement `InvoiceFinalized` est publié après le commit,
   pour qu'un événement ne survive jamais à une finalisation annulée.

Hors périmètre de ce module, documenté pour le lecteur :
- la numérotation des factures et les lignes de facture (`invoice_line`) restent NON DÉFINI
  (QE-FAC-15, QE-FAC-04) ; aucune colonne n'est créée pour elles ;
- le scénario de tarification utilisé pour une facture est provisoire (QE-FAC-10).
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Invoice, Plan, Subscription
from app.billing.pricing.resolution import resoudre_prix
from app.core.errors import AppError
from app.shared import events as bus

# Scénario de tarification d'une facture client (valeur provisoire, QE-FAC-10).
SCENARIO_FACTURE = "facture"
# Points de base : 10 000 points = 100 %.
POINTS_DE_BASE = 10_000
EVENEMENT_FACTURE_FINALISEE = "InvoiceFinalized"


def calculer_total(montant_minor: int, taux_taxe_bps: int) -> tuple[int, int]:
    """Renvoie `(taxe, total)` en unités mineures pour un montant HT et un taux en points de base.

    Arithmétique entière : la taxe est `montant * taux / 10 000` arrondie demi vers le haut,
    sans passer par un flottant (un flottant pourrait arrondir un centime de travers).
    """
    taxe = (montant_minor * taux_taxe_bps + POINTS_DE_BASE // 2) // POINTS_DE_BASE
    return taxe, montant_minor + taxe


async def _facture_de_l_organisation_verrouillee(db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    """Lit la facture avec verrou de ligne, seulement si elle appartient à l'organisation."""
    facture = await db.scalar(
        select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(Invoice.id == invoice_id, Subscription.organizationId == organization_id)
        .with_for_update(of=Invoice)
    )
    if facture is None:
        raise AppError(code="invoice_not_found", message="Facture introuvable.", status_code=404)
    return facture


async def finaliser_facture(
    db: AsyncSession, organization_id: uuid.UUID, actor_id: uuid.UUID, invoice_id: uuid.UUID, reason: str,
) -> Invoice:
    """Finalise un brouillon : fige prix, devise, taxe et total, écrit l'audit, publie `InvoiceFinalized`.

    Erreurs : voir la docstring du module (APPROVAL_REQUIRED, invoice_not_found,
    INVALID_TRANSITION, PRICE/CURRENCY/TAX_NOT_CONFIGURED). En cas d'erreur, rien n'est écrit.
    Retourne la facture relue après commit.
    """
    if not reason or not reason.strip():
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)
    facture = await _facture_de_l_organisation_verrouillee(db, organization_id, invoice_id)
    if facture.status != "draft":
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    abonnement = await db.get(Subscription, facture.subscriptionId)
    plan = await db.get(Plan, abonnement.planId)
    prix = await resoudre_prix(db, organization_id=organization_id, object_code=plan.code, scenario=SCENARIO_FACTURE)
    taxe, total = calculer_total(prix.amount_minor, prix.tax_rate_bps)
    maintenant = datetime.now(timezone.utc)
    avant = {"status": facture.status, "total": None}
    facture.status = "finalized"
    facture.currency = prix.currency
    facture.total = total
    facture.taxSnapshot = {**prix.as_snapshot(), "taxAmountMinor": taxe}
    facture.finalizedAt = maintenant
    facture.version = facture.version + 1
    await record_audit_entry(
        db, organization_id, actor_id,
        action="billing.invoice.finalize", scope="payeur",
        target_type="Invoice", target_id=facture.id,
        before_json=avant, after_json={"status": "finalized", "total": total},
        summary=f"Finalisation de la facture {facture.id}", reason=reason.strip(),
    )
    await db.commit()
    await db.refresh(facture)
    await bus.publish(EVENEMENT_FACTURE_FINALISEE, invoice_id=str(facture.id), organization_id=str(organization_id), total=total)
    return facture


async def lire_facture(db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    """Lit une facture de l'organisation ; hors périmètre, 404 `invoice_not_found` comme une absente (BE-027)."""
    facture = await db.scalar(
        select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(Invoice.id == invoice_id, Subscription.organizationId == organization_id)
    )
    if facture is None:
        raise AppError(code="invoice_not_found", message="Facture introuvable.", status_code=404)
    return facture
