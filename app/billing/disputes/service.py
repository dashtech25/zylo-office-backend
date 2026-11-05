"""Effets et lecture des litiges fournisseur (BE-094).

`appliquer_evenement_litige` est appelée par `traiter_evenement_webhook` (BE-029) dans la
transaction de l'évènement : elle ajoute ou modifie des lignes sans `commit`, pour que la ligne
d'idempotence et l'effet du litige soient écrits ensemble, ou pas du tout.

`lire_litige` applique le contrôle d'accès dans l'ordre : permission `billing.dispute.read`
d'abord (sinon `FORBIDDEN`, aucune lecture), puis périmètre du tenant. Un litige d'un autre tenant
et un identifiant inexistant produisent la même réponse `dispute_not_found` (404).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Dispute, Invoice, PaymentAttempt, Subscription
from app.billing.permissions import BILLING_DISPUTE_READ
from app.billing.subscriptions.etats import TRANSITIONS_INCIDENT
from app.core.errors import AppError
from app.rbac.service import user_has_permission

TYPE_LITIGE_OUVERT = "dispute.opened"
TYPE_LITIGE_CLOS = "dispute.resolved"
TYPES_EVENEMENT_LITIGE = frozenset({TYPE_LITIGE_OUVERT, TYPE_LITIGE_CLOS})
# Issues de clôture reconnues. Toute autre valeur de statut fournisseur est ignorée.
ISSUES_DE_CLOTURE = frozenset({"won", "lost", "withdrawn"})
# Statuts d'un litige encore ouvert : seuls ceux-ci peuvent être clos.
STATUTS_OUVERTS = ("opened", "evidence_due", "under_review")
INCIDENT_LITIGE = "disputed"
INCIDENT_SANS = "none"


async def _abonnement_de_la_tentative(db: AsyncSession, tentative_id: uuid.UUID) -> Subscription | None:
    """Abonnement dont une facture porte la tentative de paiement, ou `None`."""
    return await db.scalar(
        select(Subscription)
        .join(Invoice, Invoice.subscriptionId == Subscription.id)
        .join(PaymentAttempt, PaymentAttempt.invoiceId == Invoice.id)
        .where(PaymentAttempt.id == tentative_id)
    )


async def appliquer_evenement_litige(
    db: AsyncSession,
    tentative: PaymentAttempt,
    type_evenement: str,
    statut: str,
    reference_litige: str | None,
) -> str:
    """Applique un évènement de litige à la tentative visée ; renvoie l'`outcome` à enregistrer.

    - `dispute.opened` : crée le litige en `opened` (refusé s'il existe déjà pour cette référence)
      et passe l'incident à `disputed` si la transition est permise. Renvoie `applied`.
    - `dispute.resolved` : clôt le litige ouvert de cette tentative avec l'issue `statut`
      (`won`, `lost`, `withdrawn`), et remet l'incident à `none` s'il ne reste aucun litige
      ouvert. Renvoie `applied`. Litige déjà clos : `ignored_state`.
    - référence absente, issue inconnue ou litige introuvable : `ignored`.

    Aucune écriture de remboursement n'est faite ici (CA-2 de BE-094).
    """
    if not reference_litige:
        return "ignored"
    maintenant = datetime.now(timezone.utc)

    if type_evenement == TYPE_LITIGE_OUVERT:
        existant = await db.scalar(select(Dispute).where(Dispute.providerRef == reference_litige))
        if existant is not None:
            return "ignored_state"
        db.add(Dispute(
            paymentAttemptId=tentative.id, status="opened", providerRef=reference_litige, openedAt=maintenant,
        ))
        abonnement = await _abonnement_de_la_tentative(db, tentative.id)
        if abonnement is not None and INCIDENT_LITIGE in TRANSITIONS_INCIDENT.get(abonnement.incidentStatus, frozenset()):
            abonnement.incidentStatus = INCIDENT_LITIGE
            abonnement.version += 1
        return "applied"

    if type_evenement == TYPE_LITIGE_CLOS:
        if statut not in ISSUES_DE_CLOTURE:
            return "ignored"
        litige = await db.scalar(select(Dispute).where(
            Dispute.providerRef == reference_litige, Dispute.paymentAttemptId == tentative.id,
        ))
        if litige is None:
            return "ignored"
        if litige.status not in STATUTS_OUVERTS:
            return "ignored_state"
        litige.status = statut
        litige.resolvedAt = maintenant
        abonnement = await _abonnement_de_la_tentative(db, tentative.id)
        if abonnement is not None and abonnement.incidentStatus == INCIDENT_LITIGE:
            # Autoflush : le litige qui vient d'être clos n'est plus compté comme ouvert.
            encore_ouverts = await db.scalar(
                select(func.count())
                .select_from(Dispute)
                .join(PaymentAttempt, PaymentAttempt.id == Dispute.paymentAttemptId)
                .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
                .where(Invoice.subscriptionId == abonnement.id, Dispute.status.in_(STATUTS_OUVERTS))
            )
            if encore_ouverts == 0 and INCIDENT_SANS in TRANSITIONS_INCIDENT[INCIDENT_LITIGE]:
                abonnement.incidentStatus = INCIDENT_SANS
                abonnement.version += 1
        return "applied"

    return "ignored"


async def lire_litige(
    db: AsyncSession, *, demandeur_id: uuid.UUID, organization_id: uuid.UUID, dispute_id: uuid.UUID,
) -> Dispute:
    """Litige de l'organisation courante, après contrôle de la permission `billing.dispute.read`.

    Sans permission : `FORBIDDEN` (403), aucune lecture. Litige absent ou d'un autre tenant :
    `dispute_not_found` (404), réponse identique (CA-4 de BE-094).
    """
    if not await user_has_permission(db, demandeur_id, organization_id, BILLING_DISPUTE_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    litige = await db.scalar(
        select(Dispute)
        .join(PaymentAttempt, PaymentAttempt.id == Dispute.paymentAttemptId)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(
            Dispute.id == dispute_id,
            func.coalesce(Subscription.beneficiaryTenantId, Subscription.organizationId) == organization_id,
        )
    )
    if litige is None:
        raise AppError(code="dispute_not_found", message="Litige introuvable.", status_code=404)
    return litige
