"""Réconciliation des paiements et résultats incertains (BE-095).

Ordre des contrôles et des écritures d'un lancement `lancer_reconciliation` :
1. Permission `billing.reconciliation.run` (finance, ACTF-09) : sinon `FORBIDDEN`. Aucune écriture,
   aucun appel fournisseur (CA-3).
2. Sélection des tentatives `unknown` du seul tenant demandé, sur les deux chaînes (facture par
   abonnement, checkout par devis). Un autre tenant n'est jamais lu (CA-4).
3. Pour chaque tentative : recherche auprès du fournisseur sous la référence interne de la
   tentative (`str(id)`, la même que pour la capture). La réconciliation n'appelle JAMAIS `charge`
   (CA-1, non-double-débit).
   - le fournisseur confirme un débit (`True`) : un écart `reconciliation_difference` est créé et
     l'évènement `ReconciliationDifferenceDetected` est écrit dans l'outbox (CA-2) ;
   - pas de trace (`False`) : aucun écart, la tentative reste `unknown` pour une prochaine réconciliation ;
   - fournisseur indisponible, non implémenté ou délai dépassé : aucune conclusion, la tentative
     reste `unknown`. Ce sont les seuls cas où l'exception est absorbée ; toute autre erreur remonte.
4. Run `completed`, entrée d'audit `billing.reconciliation.run`, puis commit unique : run, écarts,
   évènements et audit sont committés ensemble (ou pas du tout).

Aucune correction automatique : le statut des tentatives n'est jamais modifié ici (CA-2).
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.events.emission import emettre_evenement_facturation
from app.billing.models import Checkout, Invoice, PaymentAttempt, Quote, ReconciliationDifference, ReconciliationRun, Subscription
from app.billing.payment_provider import PaymentProvider
from app.billing.permissions import BILLING_RECONCILIATION_RUN
from app.core.errors import AppError
from app.rbac.service import user_has_permission

DELAI_FOURNISSEUR_SECONDES = 30.0
STATUT_TENTATIVE_INCONNUE = "unknown"
STATUT_RUN_TERMINE = "completed"
STATUT_ECART_DETECTE = "detected"
TYPE_EVENEMENT_ECART = "Billing.ReconciliationDifferenceDetected"
PERIMETRE_TENANT = "tenant"


async def _tentatives_inconnues_du_tenant(db: AsyncSession, organization_id: uuid.UUID) -> list[PaymentAttempt]:
    """Tentatives `unknown` rattachées à une facture ou à un checkout du tenant, sans lire les autres.

    Deux requêtes, car une tentative porte soit une facture, soit un checkout (BE-028 / BE-082) ;
    aucune tentative ne peut apparaître deux fois.
    """
    par_facture = await db.scalars(
        select(PaymentAttempt)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(PaymentAttempt.status == STATUT_TENTATIVE_INCONNUE, Subscription.organizationId == organization_id)
    )
    par_checkout = await db.scalars(
        select(PaymentAttempt)
        .join(Checkout, Checkout.id == PaymentAttempt.checkoutId)
        .join(Quote, Quote.id == Checkout.quoteId)
        .where(PaymentAttempt.status == STATUT_TENTATIVE_INCONNUE, Quote.beneficiaryTenantId == organization_id)
    )
    return list(par_facture.all()) + list(par_checkout.all())


def _enveloppe_ecart(organization_id: uuid.UUID, actor_user_id: uuid.UUID, run_id: uuid.UUID, tentative_id: uuid.UUID, now: datetime) -> dict:
    """Enveloppe BE-150 de `ReconciliationDifferenceDetected`. Le payload ne porte aucun secret ni donnée de carte."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": TYPE_EVENEMENT_ECART,
        "schemaVersion": 1,
        "occurredAt": now.isoformat(),
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"userId": str(actor_user_id)},
        "subject": {"type": "PaymentAttempt", "id": str(tentative_id)},
        "dataClassification": "internal",
        "correlationId": f"reconciliation-{run_id}",
        "causationId": None,
        "payload": {"reconciliationRunId": str(run_id), "paymentAttemptId": str(tentative_id), "status": STATUT_ECART_DETECTE},
    }


async def lancer_reconciliation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    scope: str,
    period_key: str | None,
    fournisseur: PaymentProvider,
) -> ReconciliationRun:
    """Lance une réconciliation du tenant `organization_id` et renvoie le run committé.

    Erreurs : `FORBIDDEN` sans la permission (CA-3). Aucune autre erreur n'est levée pour un
    fournisseur indisponible : les tentatives restent `unknown` et le run est `completed`.
    """
    if not await user_has_permission(db, actor_user_id, organization_id, BILLING_RECONCILIATION_RUN):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    maintenant = datetime.now(timezone.utc)
    run = ReconciliationRun(
        organizationId=organization_id, scope=scope, periodKey=period_key,
        status=STATUT_RUN_TERMINE, differenceCount=0, startedAt=maintenant,
    )
    db.add(run)
    await db.flush()

    for tentative in await _tentatives_inconnues_du_tenant(db, organization_id):
        try:
            # CA-1 : recherche sous la même référence que la capture ; jamais de `charge` ici.
            confirme = await asyncio.wait_for(fournisseur.rechercher(str(tentative.id)), timeout=DELAI_FOURNISSEUR_SECONDES)
        except (AppError, NotImplementedError, TimeoutError, asyncio.TimeoutError):
            continue
        if not confirme:
            continue
        # CA-2 : constat seulement, la tentative n'est pas modifiée.
        db.add(ReconciliationDifference(runId=run.id, paymentAttemptId=tentative.id, status=STATUT_ECART_DETECTE))
        run.differenceCount += 1
        await emettre_evenement_facturation(
            db, _enveloppe_ecart(organization_id, actor_user_id, run.id, tentative.id, maintenant), emetteur_tenant=organization_id,
        )

    await record_audit_entry(
        db, organization_id, actor_user_id,
        action="billing.reconciliation.run", scope=PERIMETRE_TENANT,
        target_type="ReconciliationRun", target_id=run.id,
        before_json=None,
        after_json={"status": STATUT_RUN_TERMINE, "differenceCount": run.differenceCount, "scope": scope},
        summary=f"Réconciliation {run.id} : {run.differenceCount} écart(s)",
    )
    await db.commit()
    await db.refresh(run)
    return run
