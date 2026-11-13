"""Service de réactivation d'abonnement après incident ou résiliation (BE-092).

Fonction publique : `reactiver_abonnement(db, subscription_id, tenant_id, *, payment_attempt_id)`.

Ordre des contrôles, qui est aussi l'ordre des écritures :
1. Abonnement absent ou hors du tenant bénéficiaire : `subscription_not_found` (404), même réponse
   que l'inexistant (CA-4).
2. Éligibilité, avant tout examen du paiement : `INVALID_TRANSITION` (409) si l'abonnement est clos
   (`close_pending`, `subscription_closed`), si l'incident est `disputed` ou `incomplete` (un litige
   ou une facture incomplète se traitent autrement), ou si rien n'est à réactiver (cycle de vie hors
   de `REACTIVATION_CYCLE` et incident hors de `REACTIVATION_INCIDENT`). Rien n'est modifié (CA-2).
3. Paiement confirmé : la tentative doit être rattachée à une facture de cet abonnement (même
   chaîne que BE-091). Absente : `payment_attempt_not_found` (404). Issue `unknown` :
   `RECONCILIATION_REQUIRED`. Toute autre issue que `succeeded` : `PAYMENT_DECLINED` (CA-1).
4. Écriture, dans une seule transaction avec verrou de ligne et incrément de `version` (BE-072) :
   - cycle de vie `cancel_scheduled`, `cancelled` ou `expired` -> `active`, avec remise à blanc de
     `cancelMode` et `cancelEffectiveAt` ;
   - incident `past_due`, `grace` ou `suspended` -> `none`.
   Les autres axes (`financialStatus`) ne sont pas touchés.
5. Émission de `SubscriptionActivated` dans l'outbox (BE-074). L'identifiant d'évènement dérive de
   la tentative et d'un préfixe propre à la réactivation : un même paiement ne produit pas deux
   évènements, mais une activation BE-084 et une réactivation ne se confondent pas.

Choix (recommandations appliquées, consignées dans POINTS-OUVERTS) :
- le cycle de vie `cancelled` et `expired` peut revenir à `active` : la table de BE-079 ne le
  prévoit pas ; cette règle est locale à BE-092 et la table `TRANSITIONS_CYCLE_DE_VIE` n'est pas
  modifiée ;
- aucune synchronisation des droits (BE-085) n'est lancée ici : la fiche ne la demande pas.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.events.emission import emettre_evenement_facturation
from app.billing.models import Invoice, PaymentAttempt, Subscription
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.errors import AppError

ETAT_CYCLE_ACTIF = "active"
# Cycles de vie réactivables, qui reviennent à `active`. `active` seul est déjà actif.
REACTIVATION_CYCLE = frozenset({"cancel_scheduled", "cancelled", "expired"})
# Cycles de vie qui ne se réactivent jamais : l'abonnement est en clôture ou clos.
CYCLES_CLOS = frozenset({"close_pending", "subscription_closed"})
# Incidents levés par la réactivation, qui reviennent à `none`.
REACTIVATION_INCIDENT = frozenset({"past_due", "grace", "suspended"})
# Incidents qui ne se lèvent pas par un simple paiement (litige, facture incomplète).
INCIDENTS_BLOQUANTS = frozenset({"disputed", "incomplete"})
INCIDENT_SANS = "none"
STATUT_TENTATIVE_CONFIRMEE = "succeeded"
STATUT_TENTATIVE_INCONNUE = "unknown"
TYPE_EVENEMENT_ACTIVATION = "SubscriptionActivated"
VERSION_SCHEMA_ACTIVATION = 1
ACTEUR_SYSTEME = "billing.reactivation"
PREFIXE_EVENEMENT_REACTIVATION = "SubscriptionReactivated"


async def reactiver_abonnement(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    payment_attempt_id: uuid.UUID,
) -> Subscription:
    """Réactive un abonnement après incident ou résiliation, sur présentation d'un paiement confirmé.

    Renvoie l'abonnement mis à jour. Les erreurs et leur ordre sont décrits dans la docstring du
    module. En cas d'erreur, aucune écriture n'est committée.
    La permission `billing.subscription.manage` est vérifiée par la route, avant cet appel.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    _verifier_eligibilite(abonnement)

    tentative = await db.scalar(
        select(PaymentAttempt)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .where(PaymentAttempt.id == payment_attempt_id, Invoice.subscriptionId == abonnement.id)
    )
    if tentative is None:
        raise AppError(code="payment_attempt_not_found", message="Tentative de paiement introuvable.", status_code=404)
    if tentative.status == STATUT_TENTATIVE_INCONNUE:
        raise billing_error(BillingErrorCode.RECONCILIATION_REQUIRED)
    if tentative.status != STATUT_TENTATIVE_CONFIRMEE:
        raise billing_error(BillingErrorCode.PAYMENT_DECLINED)

    if abonnement.lifecycleStatus in REACTIVATION_CYCLE:
        abonnement.lifecycleStatus = ETAT_CYCLE_ACTIF
        abonnement.cancelMode = None
        abonnement.cancelEffectiveAt = None
    if abonnement.incidentStatus in REACTIVATION_INCIDENT:
        abonnement.incidentStatus = INCIDENT_SANS
    abonnement.version += 1

    try:
        await emettre_evenement_facturation(
            db,
            _enveloppe_reactivation(tenant_id, tentative, abonnement),
            emetteur_tenant=tenant_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(abonnement)
    return abonnement


def _verifier_eligibilite(abonnement: Subscription) -> None:
    """Lève `INVALID_TRANSITION` si l'abonnement ne peut pas être réactivé (CA-2 et règles de l'état).

    Un abonnement est réactivable si son cycle de vie est `active` ou réactivable, et si au moins
    une des deux conditions suivantes est vraie : le cycle est réactivable, ou l'incident est levable.
    """
    if abonnement.lifecycleStatus in CYCLES_CLOS:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    if abonnement.incidentStatus in INCIDENTS_BLOQUANTS:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    cycle_ok = abonnement.lifecycleStatus == ETAT_CYCLE_ACTIF or abonnement.lifecycleStatus in REACTIVATION_CYCLE
    if not cycle_ok:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    if abonnement.lifecycleStatus == ETAT_CYCLE_ACTIF and abonnement.incidentStatus not in REACTIVATION_INCIDENT:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)


def _enveloppe_reactivation(
    tenant_id: uuid.UUID, tentative: PaymentAttempt, abonnement: Subscription
) -> dict:
    """Enveloppe BE-150 de `SubscriptionActivated` émise par une réactivation.

    L'identifiant d'évènement est dérivé de la tentative, avec un préfixe propre à BE-092 : il ne
    peut pas entrer en collision avec l'évènement de BE-084 pour le même paiement. Le payload ne
    porte que des identifiants et des états, jamais de donnée de carte.
    """
    return {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIXE_EVENEMENT_REACTIVATION}:{tentative.id}")),
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
            "lifecycleStatus": abonnement.lifecycleStatus,
            "incidentStatus": abonnement.incidentStatus,
            "reactivation": True,
        },
    }
