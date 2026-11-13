"""Service de résiliation d'abonnement (BE-090).

Ce module est la seule porte d'écriture de la résiliation. Il réutilise, sans les
redéfinir :
- `charger_abonnement_du_tenant` et la table `TRANSITIONS_CYCLE_DE_VIE` de
  app/billing/subscriptions/etats.py (BE-079) : la résiliation est une transition de
  l'axe `lifecycle` (`active` -> `cancel_scheduled`), et seul cet axe est écrit ;
- `record_audit_entry` de app/billing/audit.py (BE-073) : une résiliation est un geste
  sensible, donc un motif est exigé et l'entrée avant/après est écrite.

Règles :
- Résiliation à échéance (`end_of_period`, mode par défaut) : l'axe lifecycle passe à
  `cancel_scheduled`, `cancelEffectiveAt` reçoit `endDate`. Rien n'est coupé avant
  l'échéance : `endDate`, les axes financier et incident, et les droits restent inchangés.
- Résiliation immédiate (`immediate`) : refusée par `INVALID_TRANSITION` tant que
  QE-FAC-08 n'est pas tranché (recommandation appliquée : mode `immediate` refusé). Aucun
  remboursement au prorata n'est calculé ici.
- Une transition absente de la table lifecycle (par exemple depuis `trialing`, ou une
  seconde résiliation) renvoie `INVALID_TRANSITION` et ne modifie rien.
- Une seule transaction : l'état, `version` (BE-072) et l'entrée d'audit sont validés
  ensemble. Si l'audit refuse (motif absent : `APPROVAL_REQUIRED`), la transaction est
  annulée et l'abonnement reste inchangé.
- Le périmètre est le tenant bénéficiaire ; un abonnement d'un autre tenant ou inexistant
  renvoie `subscription_not_found` (même réponse, CA-4).

La vérification de la permission `billing.subscription.manage` est faite par la route
(app/billing/cancellation/router.py) avant d'appeler ce service.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Subscription
from app.billing.subscriptions.etats import TRANSITIONS_CYCLE_DE_VIE, charger_abonnement_du_tenant
from app.core.errors import AppError

# Modes acceptés par la route. `immediate` est reconnu mais refusé (QE-FAC-08).
MODE_FIN_DE_PERIODE = "end_of_period"
MODE_IMMEDIAT = "immediate"
MODES_RESILIATION = frozenset({MODE_FIN_DE_PERIODE, MODE_IMMEDIAT})

# Action d'audit : résiliation, geste sensible de BE-073 (`GESTES_SENSIBLES`).
ACTION_AUDIT_RESILIATION = "billing.subscription.terminate"


async def resilier_abonnement(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    cancel_mode: str = MODE_FIN_DE_PERIODE,
    reason: str | None = None,
) -> Subscription:
    """Demande la résiliation de l'abonnement et renvoie l'abonnement mis à jour.

    Paramètres :
    - `tenant_id` : tenant bénéficiaire courant (périmètre, CA-4) ;
    - `actor_id` : utilisateur qui demande la résiliation (entrée d'audit) ;
    - `cancel_mode` : `end_of_period` (défaut) ou `immediate` (refusé) ;
    - `reason` : motif, exigé par l'audit de BE-073 (absent ou blanc : `APPROVAL_REQUIRED`).

    Erreurs :
    - `subscription_not_found` (404) : abonnement absent ou hors du tenant ;
    - `INVALID_TRANSITION` (409) : mode `immediate`, ou transition lifecycle non permise ;
    - `APPROVAL_REQUIRED` : motif absent ; rien n'est écrit dans ce cas.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    if cancel_mode == MODE_IMMEDIAT:
        raise billing_error(
            BillingErrorCode.INVALID_TRANSITION,
            "La résiliation immédiate n'est pas encore disponible ; choisissez la fin de période.",
        )
    if cancel_mode not in MODES_RESILIATION:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    etat_avant = abonnement.lifecycleStatus
    if "cancel_scheduled" not in TRANSITIONS_CYCLE_DE_VIE.get(etat_avant, frozenset()):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    avant = {"lifecycleStatus": etat_avant, "cancelMode": abonnement.cancelMode, "version": abonnement.version}
    abonnement.lifecycleStatus = "cancel_scheduled"
    abonnement.cancelMode = cancel_mode
    abonnement.cancelEffectiveAt = abonnement.endDate
    abonnement.version += 1
    apres = {"lifecycleStatus": abonnement.lifecycleStatus, "cancelMode": cancel_mode, "version": abonnement.version}

    try:
        await record_audit_entry(
            db,
            tenant_id,
            actor_id,
            action=ACTION_AUDIT_RESILIATION,
            scope="tenant",
            target_type="Subscription",
            target_id=abonnement.id,
            before_json=avant,
            after_json=apres,
            reason=reason,
        )
    except Exception:
        # Motif refusé ou audit en échec : l'abonnement doit rester exactement tel qu'il était.
        await db.rollback()
        raise

    await db.commit()
    await db.refresh(abonnement)
    return abonnement
