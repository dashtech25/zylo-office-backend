"""Service de confirmation d'abonnement (BE-084).

Ordre des contrôles, qui est aussi l'ordre des écritures :
1. Tentative de paiement du tenant : jointure sur `quote.beneficiaryTenantId`. Une tentative
   hors tenant, inconnue ou sans checkout renvoie `payment_attempt_not_found` (404) : aucune
   information n'est révélée sur les autres tenants (CA-4).
2. Statut de la tentative : `unknown` renvoie `RESULT_UNKNOWN` ; tout autre statut que
   `succeeded` renvoie `INVALID_TRANSITION` (409). Rien n'est modifié (CA-3).
3. Abonnement cible : unique abonnement `pending` du tenant bénéficiaire, payé par le payeur du
   devis (CA-4). Aucun candidat : `subscription_not_found` (404). Plusieurs : `INVALID_TRANSITION`.
4. Transition `pending -> active` vérifiée contre `TRANSITIONS_CYCLE_DE_VIE`, avec verrou de
   ligne et incrément de `version` (BE-072). Seul l'axe cycle de vie change.
5. Émission de `SubscriptionActivated` dans l'outbox (BE-074), puis un seul commit.

Reprise (CA-2) : si le commit échoue, ou si l'émission lève une erreur, la transaction est
annulée et l'abonnement reste `pending`. Un nouvel appel refait la même écriture locale. La
fonction ne reçoit aucun fournisseur : la capture n'est jamais relancée. Un appel après
succès ne réémet rien, car l'abonnement n'est plus `pending` : il renvoie `subscription_not_found`.

Écart à consigner : le lien checkout -> abonnement n'est pas une colonne (QE-FAC-04). La
recherche par tenant et payeur est la recommandation appliquée dans cette tâche.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.events.emission import emettre_evenement_facturation
from app.billing.models import Checkout, PaymentAttempt, Quote, Subscription
from app.billing.subscriptions.etats import TRANSITIONS_CYCLE_DE_VIE
from app.core.errors import AppError

STATUT_TENTATIVE_CONFIRMEE = "succeeded"
STATUT_TENTATIVE_INCONNUE = "unknown"
ETAT_CYCLE_EN_ATTENTE = "pending"
ETAT_CYCLE_ACTIF = "active"
TYPE_EVENEMENT_ACTIVATION = "SubscriptionActivated"
VERSION_SCHEMA_ACTIVATION = 1
ACTEUR_SYSTEME = "billing.activation"


async def confirmer_abonnement(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payment_attempt_id: uuid.UUID,
) -> Subscription:
    """Passe l'abonnement du checkout à `active` pour une tentative `succeeded`, et émet l'évènement.

    Renvoie l'abonnement activé. Les erreurs et leur ordre sont décrits dans la docstring du module.
    Aucune écriture n'est committée en cas d'erreur, y compris si l'émission de l'évènement échoue.
    """
    tentative = await db.scalar(
        select(PaymentAttempt)
        .join(Checkout, Checkout.id == PaymentAttempt.checkoutId)
        .join(Quote, Quote.id == Checkout.quoteId)
        .where(PaymentAttempt.id == payment_attempt_id, Quote.beneficiaryTenantId == tenant_id)
    )
    if tentative is None:
        raise AppError(code="payment_attempt_not_found", message="Tentative de paiement introuvable.", status_code=404)
    if tentative.status == STATUT_TENTATIVE_INCONNUE:
        raise billing_error(BillingErrorCode.RESULT_UNKNOWN)
    if tentative.status != STATUT_TENTATIVE_CONFIRMEE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    checkout = await db.get(Checkout, tentative.checkoutId)
    devis = await db.get(Quote, checkout.quoteId)

    candidats = (await db.scalars(
        select(Subscription)
        .where(
            Subscription.beneficiaryTenantId == tenant_id,
            Subscription.payerId == devis.payerId,
            Subscription.lifecycleStatus == ETAT_CYCLE_EN_ATTENTE,
        )
        .with_for_update()
    )).all()
    if not candidats:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    if len(candidats) > 1:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    abonnement = candidats[0]

    if ETAT_CYCLE_ACTIF not in TRANSITIONS_CYCLE_DE_VIE.get(abonnement.lifecycleStatus, frozenset()):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    abonnement.lifecycleStatus = ETAT_CYCLE_ACTIF
    abonnement.version += 1

    try:
        await emettre_evenement_facturation(
            db,
            _enveloppe_activation(tenant_id, tentative, checkout, abonnement),
            emetteur_tenant=tenant_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(abonnement)
    return abonnement


def _enveloppe_activation(
    tenant_id: uuid.UUID,
    tentative: PaymentAttempt,
    checkout: Checkout,
    abonnement: Subscription,
) -> dict[str, Any]:
    """Enveloppe brute de `SubscriptionActivated` (BE-150).

    L'identifiant d'évènement est dérivé de la tentative : une seconde émission pour le même
    paiement est refusée par l'unicité de `eventId` au lieu de créer un doublon. Le payload ne
    porte que des identifiants, jamais de donnée de carte.
    """
    return {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{TYPE_EVENEMENT_ACTIVATION}:{tentative.id}")),
        "eventType": TYPE_EVENEMENT_ACTIVATION,
        "schemaVersion": VERSION_SCHEMA_ACTIVATION,
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "tenantId": str(tenant_id),
        "scope": {"type": "organization", "id": str(tenant_id)},
        "actor": {"system": ACTEUR_SYSTEME},
        "subject": {"type": "Subscription", "id": str(abonnement.id)},
        "dataClassification": "internal",
        "correlationId": str(tentative.id),
        "causationId": None,
        "payload": {
            "subscriptionId": str(abonnement.id),
            "paymentAttemptId": str(tentative.id),
            "checkoutId": str(checkout.id),
            "lifecycleStatus": ETAT_CYCLE_ACTIF,
        },
    }
