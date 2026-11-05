"""Service des incidents de paiement : axe `incidentStatus` (BE-091).

Fonctions publiques :
- `appliquer_echec_paiement(db, *, tenant_id, subscription_id, tentative_id)` : traitement
  système d'une tentative `failed` rattachée à une facture de l'abonnement. Pose
  `incidentStatus = past_due`, émet `Billing.PaymentAttemptFailed` dans l'outbox, dans la même
  transaction (CA-1). Ne touche ni `lifecycleStatus` ni `financialStatus`, et n'appelle aucune
  synchronisation des droits (CA-2).
- `suspendre_manuellement(db, *, actor_user_id, tenant_id, subscription_id)` : passe l'axe incident
  à `suspended` pour un acteur ayant `billing.subscription.manage` (CA-3).

Ordre des contrôles de `appliquer_echec_paiement` :
1. abonnement hors du tenant ou inexistant : `subscription_not_found` (404), sans écriture (CA-4) ;
2. tentative absente de l'abonnement (pas de facture de cet abonnement) : `payment_attempt_not_found` (404) ;
3. tentative non `failed` : `INVALID_TRANSITION` (409). Une tentative `unknown` n'est jamais un échec ;
4. incident courant `none` : passage à `past_due` ; incident déjà `past_due` : pas de transition, mais
   l'événement est (ré)émis, sans doublon, car son identifiant est déterministe (rejeu sûr) ;
5. tout autre incident (`suspended`, `disputed`, `incomplete`, `grace`) : `INVALID_TRANSITION`.

Choix (recommandations appliquées, à consigner dans POINTS-OUVERTS) :
- permission de suspension manuelle : `billing.subscription.manage`, déjà accordée au propriétaire
  (QE-FAC-07 ne tranche pas le rôle) ;
- événement émis à l'échec seulement : `Billing.PaymentAttemptFailed`. Le « submitted » n'est pas
  émis par BE-082 à ce jour et reste hors périmètre de BE-091.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.events.emission import emettre_evenement_facturation
from app.billing.models import Invoice, PaymentAttempt, Subscription
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.subscriptions.etats import charger_abonnement_du_tenant, transition_etat
from app.core.errors import AppError
from app.rbac.service import user_has_permission

TYPE_EVENEMENT_ECHEC_PAIEMENT = "Billing.PaymentAttemptFailed"
STATUT_TENTATIVE_ECHOUEE = "failed"
INCIDENT_SANS = "none"
INCIDENT_IMPAYE = "past_due"
AXE_INCIDENT = "incident"
CIBLE_SUSPENDU = "suspended"


async def appliquer_echec_paiement(
    db: AsyncSession, *, tenant_id: uuid.UUID, subscription_id: uuid.UUID, tentative_id: uuid.UUID
) -> Subscription:
    """Traite l'échec d'une tentative : `incidentStatus` passe à `past_due`, l'événement part dans l'outbox.

    Traitement système (aucun acteur humain). Une seule transaction : la transition de l'axe et
    l'événement sont committés ensemble, ou rien ne l'est. Voir l'ordre des contrôles dans le module.
    Le rejeu d'un même échec ne crée pas de second événement (identifiant d'événement déterministe).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    tentative = await db.scalar(
        select(PaymentAttempt)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .where(PaymentAttempt.id == tentative_id, Invoice.subscriptionId == abonnement.id)
    )
    if tentative is None:
        raise AppError(code="payment_attempt_not_found", message="Tentative de paiement introuvable.", status_code=404)
    if tentative.status != STATUT_TENTATIVE_ECHOUEE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    # Seul `none` ouvre un impayé ; `past_due` (rejeu, second échec) ne transite pas mais réémet
    # l'événement, sans doublon. Tout autre incident est une transition non prévue (BE-079).
    if abonnement.incidentStatus not in (INCIDENT_SANS, INCIDENT_IMPAYE):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    if abonnement.incidentStatus == INCIDENT_SANS:
        abonnement.incidentStatus = INCIDENT_IMPAYE
        abonnement.version += 1

    maintenant = datetime.now(timezone.utc)
    try:
        await emettre_evenement_facturation(
            db, _enveloppe_echec(tenant_id, abonnement, tentative, maintenant), emetteur_tenant=tenant_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(abonnement)
    return abonnement


async def suspendre_manuellement(
    db: AsyncSession, *, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, subscription_id: uuid.UUID
) -> Subscription:
    """Passe l'axe incident à `suspended` sur demande d'une personne habilitée.

    Permission `billing.subscription.manage` vérifiée avant toute lecture de l'abonnement : sans elle,
    `FORBIDDEN` et aucune écriture (CA-3). Le périmètre est le tenant ; hors périmètre, la réponse est
    celle de l'inexistant (CA-4, voir `transition_etat`). Aucun droit n'est retiré : la suspension
    d'incident ne déclenche aucune synchronisation des droits.
    """
    if not await user_has_permission(db, actor_user_id, tenant_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    return await transition_etat(db, subscription_id, tenant_id, AXE_INCIDENT, CIBLE_SUSPENDU)


def _enveloppe_echec(
    tenant_id: uuid.UUID, abonnement: Subscription, tentative: PaymentAttempt, maintenant: datetime
) -> dict:
    """Enveloppe BE-150 de `Billing.PaymentAttemptFailed`.

    L'identifiant d'événement dérive de la tentative : un rejeu produit le même `eventId`, que
    l'outbox déduplique. Traitement système : l'acteur est `{"type": "system"}`. Le payload ne porte
    aucune donnée de carte.
    """
    return {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"billing-payment-attempt-failed:{tentative.id}")),
        "eventType": TYPE_EVENEMENT_ECHEC_PAIEMENT,
        "schemaVersion": 1,
        "occurredAt": maintenant.isoformat(),
        "tenantId": str(tenant_id),
        "scope": {"type": "organization", "id": str(tenant_id)},
        "actor": {"type": "system"},
        "subject": {"type": "PaymentAttempt", "id": str(tentative.id)},
        "dataClassification": "internal",
        "correlationId": f"incident-{abonnement.id}",
        "causationId": None,
        "payload": {
            "subscriptionId": str(abonnement.id),
            "paymentAttemptId": str(tentative.id),
            "status": STATUT_TENTATIVE_ECHOUEE,
            "incidentStatus": INCIDENT_IMPAYE,
        },
    }
