"""Demande de remboursement d'un paiement réussi (BE-093).

Ordre des contrôles et des écritures d'une demande `demander_remboursement` :
1. Permission `billing.refund.request` (finance, ACTF-09) : sinon `FORBIDDEN`. Aucune écriture.
2. Paiement de l'organisation courante (facture ou checkout) : sinon `payment_not_found` (404),
   identique à un identifiant inexistant (CA-4).
3. Commande décorée par `idempotent_command` (BE-072) : même clé et même commande renvoient le
   remboursement initial sans effet de bord (CA-2) ; même clé, commande différente : `DUPLICATE`.
   Sous la réservation, dans la transaction de la commande :
   a. motif non vide sinon `APPROVAL_REQUIRED` (geste sensible, BE-073) ;
   b. approbateur renseigné, différent du demandeur et membre de l'organisation, sinon
      `APPROVAL_REQUIRED` (CA-3, QE-FAC-02) ;
   c. paiement `succeeded`, sinon `INVALID_TRANSITION` ;
   d. montant inférieur ou égal au reliquat (paiement moins remboursements `requested`, `pending`
      et `succeeded`), sinon `REFUND_LIMIT_EXCEEDED` ;
   e. ligne `refund` en `requested` + entrée d'audit `billing.refund.approve`, committées AVANT
      tout appel fournisseur (CA-1) ;
   f. ligne passée `pending`, committée, puis appel `rembourser` borné par `DELAI_FOURNISSEUR_SECONDES`.

Issues de l'appel fournisseur :
- confirmé : `succeeded` ; refusé (`False`) : `failed` ;
- `PROVIDER_UNAVAILABLE` (aucune transaction initiée) : `failed` ;
- délai dépassé ou erreur inattendue : reste `pending` (issue inconnue, à réconcilier, BE-095).
  Ce n'est jamais un échec silencieux : la ligne et la réponse 202 portent l'état réel.

Une commande refusée avant l'approbation ne consomme pas sa clé (le décorateur retire la réservation).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.credit_notes.service import _est_membre
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.idempotency import idempotent_command
from app.billing.models import Checkout, Invoice, PaymentAttempt, Quote, Refund, Subscription
from app.billing.payment_provider import PaymentProvider
from app.billing.permissions import BILLING_REFUND_REQUEST
from app.core.errors import AppError
from app.rbac.service import user_has_permission

logger = logging.getLogger(__name__)

ROUTE_REMBOURSEMENT = "billing.payment.refund.create"
DELAI_FOURNISSEUR_SECONDES = 30.0

STATUT_PAIEMENT_REUSSI = "succeeded"
STATUT_REMBOURSEMENT_DEMANDE = "requested"
STATUT_REMBOURSEMENT_EN_ATTENTE = "pending"
STATUT_REMBOURSEMENT_REUSSI = "succeeded"
STATUT_REMBOURSEMENT_ECHOUE = "failed"
# Remboursements qui comptent dans le reliquat : tout sauf les échecs.
STATUTS_ENGAGES = (STATUT_REMBOURSEMENT_DEMANDE, STATUT_REMBOURSEMENT_EN_ATTENTE, STATUT_REMBOURSEMENT_REUSSI)


async def _paiement_de_l_organisation(db: AsyncSession, organization_id: uuid.UUID, payment_id: uuid.UUID) -> PaymentAttempt:
    """Paiement rattaché à une facture ou à un checkout de l'organisation ; sinon 404 `payment_not_found`.

    Le hors périmètre et l'inexistant produisent la même erreur (CA-4).
    """
    paiement = await db.scalar(
        select(PaymentAttempt)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(PaymentAttempt.id == payment_id, Subscription.organizationId == organization_id)
    )
    if paiement is None:
        paiement = await db.scalar(
            select(PaymentAttempt)
            .join(Checkout, Checkout.id == PaymentAttempt.checkoutId)
            .join(Quote, Quote.id == Checkout.quoteId)
            .where(PaymentAttempt.id == payment_id, Quote.beneficiaryTenantId == organization_id)
        )
    if paiement is None:
        raise AppError(code="payment_not_found", message="Paiement introuvable.", status_code=404)
    return paiement


async def demander_remboursement(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payment_id: uuid.UUID,
    idempotency_key: str,
    amount: int,
    reason: str,
    approver_id: uuid.UUID | None,
    fournisseur: PaymentProvider,
) -> Refund:
    """Demande un remboursement de `amount` (unités mineures) sur le paiement `payment_id`.

    Point d'entrée public. Renvoie le remboursement dans son état final (`succeeded`, `failed` ou
    `pending` si l'issue est inconnue). Les erreurs sont décrites dans la docstring du module.
    """
    if not await user_has_permission(db, actor_user_id, organization_id, BILLING_REFUND_REQUEST):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    await _paiement_de_l_organisation(db, organization_id, payment_id)

    # Le fournisseur reste hors des arguments de la commande : son empreinte ne doit dépendre que
    # de la demande (même convention que app/billing/payment_attempts/service.py).
    @idempotent_command(route=ROUTE_REMBOURSEMENT, result_model=Refund, principal_arg="actor_user_id")
    async def commande(db: AsyncSession, *, actor_user_id: uuid.UUID, payment_id: uuid.UUID, organization_id: uuid.UUID,
                       amount: int, reason: str, approver_id: uuid.UUID | None, idempotency_key: str):
        return await _executer_remboursement(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            payment_id=payment_id,
            idempotency_key=idempotency_key,
            amount=amount,
            reason=reason,
            approver_id=approver_id,
            fournisseur=fournisseur,
        )

    return await commande(
        db, actor_user_id=actor_user_id, payment_id=payment_id, organization_id=organization_id,
        amount=amount, reason=reason, approver_id=approver_id, idempotency_key=idempotency_key,
    )


async def _executer_remboursement(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payment_id: uuid.UUID,
    idempotency_key: str,
    amount: int,
    reason: str,
    approver_id: uuid.UUID | None,
    fournisseur: PaymentProvider,
) -> Refund:
    """Corps de la commande : contrôles, approbation committée, puis envoi et issue.

    Appelée uniquement par `demander_remboursement`, sous `idempotent_command`. Le paiement est
    verrouillé (`FOR UPDATE`) pour que deux demandes concurrentes lisent le même reliquat.
    """
    motif = (reason or "").strip()
    if not motif:
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)
    if approver_id is None or approver_id == actor_user_id or not await _est_membre(db, organization_id, approver_id):
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)

    paiement = await db.get(PaymentAttempt, payment_id, with_for_update=True)
    if paiement is None or paiement.status != STATUT_PAIEMENT_REUSSI:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    deja_rembourse = await db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.paymentAttemptId == paiement.id, Refund.status.in_(STATUTS_ENGAGES),
        )
    )
    if amount > paiement.amountMinor - int(deja_rembourse):
        raise billing_error(BillingErrorCode.REFUND_LIMIT_EXCEEDED)

    remboursement = Refund(
        paymentAttemptId=paiement.id, amount=amount, currency=paiement.currency,
        status=STATUT_REMBOURSEMENT_DEMANDE, approverId=approver_id, reason=motif, request_id=idempotency_key,
    )
    db.add(remboursement)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise billing_error(BillingErrorCode.DUPLICATE) from exc
    # CA-1 : l'approbation (ligne `requested` et audit) est committée AVANT tout appel fournisseur.
    await record_audit_entry(
        db, organization_id, actor_user_id,
        action="billing.refund.approve", scope="payeur",
        target_type="Refund", target_id=remboursement.id,
        before_json=None,
        after_json={"status": STATUT_REMBOURSEMENT_DEMANDE, "amount": amount, "paymentAttemptId": str(paiement.id)},
        summary=f"Remboursement {remboursement.id} du paiement {paiement.id}", reason=motif, approver_id=approver_id,
    )
    await db.commit()
    await db.refresh(remboursement)

    remboursement.status = STATUT_REMBOURSEMENT_EN_ATTENTE
    await db.commit()

    try:
        confirme = await asyncio.wait_for(
            fournisseur.rembourser(amount, remboursement.currency, str(remboursement.id)),
            timeout=DELAI_FOURNISSEUR_SECONDES,
        )
        nouveau_statut = STATUT_REMBOURSEMENT_REUSSI if confirme else STATUT_REMBOURSEMENT_ECHOUE
    except AppError as exc:
        if exc.code == BillingErrorCode.PROVIDER_UNAVAILABLE.value:
            nouveau_statut = STATUT_REMBOURSEMENT_ECHOUE
        else:
            logger.exception("Remboursement %s : erreur fournisseur, issue inconnue", remboursement.id)
            nouveau_statut = STATUT_REMBOURSEMENT_EN_ATTENTE
    except (TimeoutError, asyncio.TimeoutError):
        nouveau_statut = STATUT_REMBOURSEMENT_EN_ATTENTE
    except Exception:
        logger.exception("Remboursement %s : erreur inattendue, issue inconnue", remboursement.id)
        nouveau_statut = STATUT_REMBOURSEMENT_EN_ATTENTE

    if nouveau_statut != STATUT_REMBOURSEMENT_EN_ATTENTE:
        remboursement.status = nouveau_statut
        await db.commit()
    await db.refresh(remboursement)
    return remboursement
