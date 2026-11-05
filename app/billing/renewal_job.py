"""Job de renouvellement d'abonnement, rejouable (BE-089). Doc de module : `app/billing/renewal_job`.

Contrat de `renouveler_abonnement` :

- Déclenchement système uniquement (ACTF-12, aucune permission utilisateur) : `declencheur`
  doit valoir `DECLENCHEUR_SYSTEME`, sinon `FORBIDDEN` avant toute lecture. Aucun identifiant
  d'utilisateur ne vaut déclenchement système.
- Un abonnement par appel, dans le périmètre `tenant_id` (même règle que
  `charger_abonnement_du_tenant`) : hors tenant ou inexistant, `subscription_not_found` (404),
  sans aucune écriture.
- Clé de déduplication : (subscriptionId, periodKey, type = `renewal`). Un passage `completed`
  déjà présent est renvoyé tel quel : ni facture, ni nouveau passage (CA-1). Un passage `refused`
  déjà présent renvoie `INVALID_TRANSITION`, sans écriture.
- Abonnement `cancelled` ou `expired` : un passage `refused` est écrit et commité (le journal
  du refus), puis `INVALID_TRANSITION` (CA-2). Aucune facture.
- Sinon : une facture `pending` au montant de la version souscrite (même source que
  `service.create_invoice`), un passage `completed` lié à cette facture, `renewedAt` renseigné,
  `version` incrémentée. Le tout dans une seule transaction.

Concurrence : la ligne d'abonnement est verrouillée (`SELECT ... FOR UPDATE`) pendant la
transaction ; deux passages concurrents pour la même période se sérialisent, et le second
relit le passage du premier. La contrainte unique `uq_renewal_run_key` reste le filet de sécurité.

Choix hors fiche (recommandations appliquées) :
- aucun `paymentAttempt` n'est créé ici : la tentative de paiement relève des parcours de
  paiement (BE-082) ; le passage de renouvellement est la « tentative » dédupliquée de BE-089 ;
- `endDate` n'est pas prolongée : la durée de la période suivante n'est pas tranchée
  (QE-FAC-04 / QE-FAC-07) ;
- la clé d'idempotence de la facture est `renewal:<subscriptionId>:<periodKey>`, unique par
  construction, donc un rejeu ne peut pas insérer une seconde facture même hors de ce module.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Invoice, Plan, PlanVersion, RenewalRun
from app.billing.service import ensure_initial_plan_version
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.errors import AppError

logger = logging.getLogger(__name__)

# Seul déclencheur accepté : le job système (ACTF-12). Toute autre valeur est un refus.
DECLENCHEUR_SYSTEME = "systeme"
# Type de passage de ce job (deuxième volet de la clé de déduplication).
TYPE_RENOUVELLEMENT = "renewal"
STATUT_TERMINE = "completed"
STATUT_REFUSE = "refused"
# États de cycle de vie après lesquels aucun renouvellement n'est possible (BE-079).
CYCLES_TERMINES = frozenset({"cancelled", "expired"})


async def renouveler_abonnement(
    db: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    period_key: str,
    declencheur: str,
) -> RenewalRun:
    """Renouvelle un abonnement pour une période, de façon idempotente. Voir le contrat du module.

    Renvoie le passage (nouveau ou déjà existant). Erreurs : `FORBIDDEN` (déclencheur non
    système), `subscription_not_found` (404), `INVALID_TRANSITION` (abonnement terminé ou
    passage déjà refusé). En cas d'erreur, aucune facture n'est émise.
    """
    if declencheur != DECLENCHEUR_SYSTEME:
        raise billing_error(BillingErrorCode.FORBIDDEN)

    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    passage = await db.scalar(select(RenewalRun).where(
        RenewalRun.subscriptionId == subscription_id,
        RenewalRun.periodKey == period_key,
        RenewalRun.type == TYPE_RENOUVELLEMENT,
    ))
    if passage is not None:
        if passage.status == STATUT_TERMINE:
            return passage
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    maintenant = datetime.now(timezone.utc)
    if abonnement.lifecycleStatus in CYCLES_TERMINES:
        db.add(RenewalRun(
            subscriptionId=subscription_id, periodKey=period_key, type=TYPE_RENOUVELLEMENT,
            status=STATUT_REFUSE, attemptedAt=maintenant, invoiceId=None,
        ))
        await db.commit()
        logger.warning(
            "renouvellement refusé : abonnement %s en cycle de vie %s, période %s",
            subscription_id, abonnement.lifecycleStatus, period_key,
        )
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    plan = await db.get(Plan, abonnement.planId)
    version = (
        await db.get(PlanVersion, abonnement.planVersionId)
        if abonnement.planVersionId else await ensure_initial_plan_version(db, plan)
    )
    facture = Invoice(
        subscriptionId=subscription_id, amountCents=version.amountMinor,
        amountMinor=version.amountMinor, currency=version.currency,
        status="pending", issuedAt=maintenant,
        idempotencyKey=f"renewal:{subscription_id}:{period_key}",
    )
    db.add(facture)
    await db.flush()
    passage = RenewalRun(
        subscriptionId=subscription_id, periodKey=period_key, type=TYPE_RENOUVELLEMENT,
        status=STATUT_TERMINE, attemptedAt=maintenant, invoiceId=facture.id,
    )
    db.add(passage)
    abonnement.renewedAt = maintenant
    abonnement.version += 1
    await db.commit()
    await db.refresh(passage)
    return passage
