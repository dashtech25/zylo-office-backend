"""Service de démarrage d'essai (BE-080).

Ordre des contrôles, qui est aussi l'ordre des écritures :
1. Permission `billing.subscription.manage` (ACTF-04 acheteur) sur le tenant courant :
   sinon `FORBIDDEN`, rien n'est lu ni écrit.
2. Abonnement du tenant bénéficiaire, sinon `subscription_not_found` (même réponse que
   l'inexistant, CA-4).
3. Transition : l'axe lifecycle doit permettre `trialing` depuis son état courant
   (`pending` en pratique), sinon `INVALID_TRANSITION`. Contrôlé avant le consentement pour
   qu'une demande refusée n'enregistre pas de consentement.
4. Consentement explicite obligatoire (recommandation approuvée 2026-11-02). Si la requête
   porte un consentement, il est enregistré via BE-076 ; ensuite, une ligne
   `consent_record` doit exister pour le compte payeur, sinon `CONSENT_REQUIRED` et rien
   n'est écrit sur l'abonnement (CA-1).
5. Écriture : `lifecycleStatus = trialing`, `startDate = maintenant`, `endDate = trialEnd`,
   `version` incrémentée. Seul l'axe lifecycle change ; `financialStatus`, `incidentStatus`
   et les droits restent inchangés (CA-5).
6. Publication de `TrialStarted` après le commit (CA-2).

Points non tranchés, traités par recommandation :
- `trialEnd` est obligatoire, avec fuseau, et stocké en UTC (QE-FAC-05). Aucune vérification
  qu'il soit postérieur à maintenant n'est faite ici ; le code d'erreur pour ce cas n'est pas
  défini dans le catalogue.
- L'événement est publié sur le bus intra-processus (BE-150), pas écrit dans une outbox
  persistée : la table `outbox_events` relève de BE-234 et n'existe pas encore. Le CA-2
  « écrit dans l'outbox » reste donc à compléter (question à ouvrir, voir POINTS-OUVERTS).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import consents
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import ConsentRecord, Subscription
from app.billing.subscriptions.etats import TRANSITIONS_CYCLE_DE_VIE, charger_abonnement_du_tenant
from app.core.errors import AppError
from app.evenements.publication import publier_enveloppe

# Type d'événement publié à l'entrée en essai. Nommé comme dans la définition (BE-080, CA-2).
TYPE_EVENEMENT_ESSAI = "TrialStarted"
VERSION_SCHEMA_ESSAI = 1


async def demarrer_essai(
    db: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    trial_end: datetime,
    consent: dict | None = None,
) -> Subscription:
    """Fait passer l'abonnement en essai (`trialing`) et renvoie la ligne mise à jour.

    Paramètres :
    - `tenant_id` : tenant bénéficiaire courant (périmètre, CA-4) ;
    - `actor_id` : utilisateur qui démarre l'essai (personne du consentement et acteur de
      l'événement) ;
    - `trial_end` : fin d'essai, datetime avec fuseau (converti en UTC) ;
    - `consent` : `{"consentTextVersion": str, "scope": str}` optionnel. Si fourni, il est
      enregistré avant le contrôle de consentement.

    Erreurs : `FORBIDDEN` (permission, vérifiée par la route avant cet appel) ;
    `subscription_not_found` (404) ; `INVALID_TRANSITION` (409) ; `CONSENT_REQUIRED` (422).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=False)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    if "trialing" not in TRANSITIONS_CYCLE_DE_VIE.get(abonnement.lifecycleStatus, frozenset()):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    if consent is not None and abonnement.payerId is not None:
        # Commit interne à BE-076 : le consentement est une preuve, il reste même si l'essai
        # n'aboutit pas ensuite.
        await consents.enregistrer_consentement(
            db,
            tenant_id=tenant_id,
            personne_id=actor_id,
            account_id=abonnement.payerId,
            consent_text_version=consent["consentTextVersion"],
            scope=consent["scope"],
            correction_of_id=None,
        )

    if not await _consentement_enregistre(db, abonnement.payerId):
        raise billing_error(BillingErrorCode.CONSENT_REQUIRED)

    # Relecture verrouillée : la transition est revérifiée sur l'état commité.
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if "trialing" not in TRANSITIONS_CYCLE_DE_VIE.get(abonnement.lifecycleStatus, frozenset()):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    maintenant = datetime.now(timezone.utc)
    abonnement.lifecycleStatus = "trialing"
    abonnement.startDate = maintenant
    abonnement.endDate = trial_end.astimezone(timezone.utc)
    abonnement.version += 1
    await db.commit()
    await db.refresh(abonnement)

    await publier_enveloppe(
        {
            "eventId": uuid.uuid4(),
            "eventType": TYPE_EVENEMENT_ESSAI,
            "schemaVersion": VERSION_SCHEMA_ESSAI,
            "occurredAt": maintenant,
            "tenantId": tenant_id,
            "scope": {"type": "tenant", "id": str(tenant_id)},
            "actor": {"type": "user", "id": str(actor_id)},
            "subject": {"type": "Subscription", "id": str(abonnement.id)},
            "dataClassification": "internal",
            "correlationId": None,
            "causationId": None,
            "payload": {
                "subscriptionId": str(abonnement.id),
                "trialEnd": abonnement.endDate.isoformat(),
            },
        },
        tenant_identite=tenant_id,
    )
    return abonnement


async def _consentement_enregistre(db: AsyncSession, payeur_id: uuid.UUID | None) -> bool:
    """Vrai si au moins une ligne de consentement existe pour le compte payeur (BE-076).

    Sans payeur rattaché, aucun consentement ne peut exister : renvoie faux.
    """
    if payeur_id is None:
        return False
    trouve = await db.scalar(select(ConsentRecord.id).where(ConsentRecord.accountId == payeur_id).limit(1))
    return trouve is not None
