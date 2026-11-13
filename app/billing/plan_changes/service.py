"""Aperçu et application d'un changement de plan (BE-088).

Ce module est la seule porte d'écriture de `plan_change`. Il réutilise, sans les
redéfinir :
- `charger_abonnement_du_tenant` (app/billing/subscriptions/etats.py, BE-079) : périmètre
  tenant, sans fuite d'existence ;
- `resoudre_prix` (app/billing/pricing/resolution.py, BE-078) : seule source d'un montant ;
- `PlanVersionSnapshot` (app/billing/models.py, BE-075) : version cible figée.

Règles :
- `apercu_changement_plan` est en lecture seule. Pour un upgrade, `financialEffects`
  porte `prorata = None`, `prorataStatus = NON_DEFINI`, et soit le prix résolu, soit le
  code d'erreur de la résolution (`PRICE_NOT_CONFIGURED`, etc.). Pour un downgrade,
  `effectiveAt` est `endDate`, et aucun effet financier n'est calculé.
- `appliquer_changement_plan` n'écrit que pour un downgrade : une ligne `plan_change` au
  statut `scheduled`, datée à `endDate`. L'abonnement n'est pas modifié (CA-1).
- Un upgrade est refusé par `INVALID_TRANSITION` (QE-FAC-05 : changement en cours de
  période refusé tant que non décidé).
- Une demande n'est possible que si le cycle de vie est `active`, et s'il n'existe pas
  déjà une demande `scheduled` pour l'abonnement (contrôle du service, puis index unique
  partiel de la base, qui rattrape la course entre deux requêtes).

Erreurs :
- `subscription_not_found` (404) : abonnement absent ou hors tenant ;
- `snapshot_not_found` (404) : instantané absent ou d'un autre tenant ;
- `INVALID_TRANSITION` (409) : upgrade appliqué, cycle de vie non `active`, ou demande
  déjà planifiée.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import PlanChange, PlanVersionSnapshot
from app.billing.pricing.resolution import resoudre_prix
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.errors import AppError

# Scénario de prix de la règle utilisée pour l'aperçu d'upgrade. Valeur provisoire :
# la liste des scénarios n'est pas fixée (QE-FAC-10).
SCENARIO_CHANGEMENT_PLAN = "changement_plan"

# Code provisoire signalant l'absence de prorata : aucune formule n'est définie
# (QE-FAC-05). Aucun montant de prorata n'est jamais calculé ni renvoyé.
PRORATA_STATUT_NON_DEFINI = "NON_DEFINI"

DIRECTION_UPGRADE = "upgrade"
DIRECTION_DOWNGRADE = "downgrade"
DIRECTIONS = frozenset({DIRECTION_UPGRADE, DIRECTION_DOWNGRADE})

STATUT_PLANIFIE = "scheduled"
CYCLE_DE_VIE_MODIFIABLE = "active"


async def _charger_instantane_du_tenant(
    db: AsyncSession, snapshot_id: uuid.UUID, tenant_id: uuid.UUID
) -> PlanVersionSnapshot:
    """Instantané de la version cible, seulement s'il appartient au tenant.

    Un instantané d'un autre tenant est traité comme absent (`snapshot_not_found`),
    sans révéler son existence.
    """
    instantane = await db.scalar(
        select(PlanVersionSnapshot).where(
            PlanVersionSnapshot.id == snapshot_id,
            PlanVersionSnapshot.organizationId == tenant_id,
        )
    )
    if instantane is None:
        raise AppError(code="snapshot_not_found", message="Version d'offre cible introuvable.", status_code=404)
    return instantane


async def apercu_changement_plan(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    target_snapshot_id: uuid.UUID,
    direction: str,
) -> dict:
    """Renvoie l'aperçu du changement sans rien écrire.

    Pour un upgrade, `financialEffects` contient le prix résolu (BE-078) ou le code
    d'erreur de la résolution, et `prorataStatus = NON_DEFINI`. Pour un downgrade,
    `financialEffects` vaut `None` et `effectiveAt` est la fin de période.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    instantane = await _charger_instantane_du_tenant(db, target_snapshot_id, tenant_id)

    apercu = {
        "subscriptionId": str(abonnement.id),
        "direction": direction,
        "targetPlanRef": instantane.planRef,
        "targetPlanVersion": instantane.planVersion,
        "effectiveAt": None,
        "financialEffects": None,
    }
    if direction == DIRECTION_DOWNGRADE:
        apercu["effectiveAt"] = abonnement.endDate
        return apercu

    # Upgrade : le prix ne vient que de BE-078. Sans règle, rien n'est inventé.
    prix_resolu = None
    code_erreur = None
    try:
        prix = await resoudre_prix(
            db,
            organization_id=tenant_id,
            object_code=instantane.planRef,
            scenario=SCENARIO_CHANGEMENT_PLAN,
        )
        prix_resolu = {
            "amountMinor": prix.amount_minor,
            "currency": prix.currency,
            "taxRateBps": prix.tax_rate_bps,
        }
    except AppError as erreur:
        code_erreur = erreur.code
    apercu["financialEffects"] = {
        "prorata": None,
        "prorataStatus": PRORATA_STATUT_NON_DEFINI,
        "resolvedPrice": prix_resolu,
        "priceErrorCode": code_erreur,
    }
    return apercu


async def appliquer_changement_plan(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    target_snapshot_id: uuid.UUID,
    direction: str,
) -> PlanChange:
    """Planifie un downgrade à `endDate` et renvoie la demande créée.

    Le verrou sur l'abonnement sérialise les demandes concurrentes. L'abonnement
    lui-même n'est pas modifié : son plan change à l'échéance, par un traitement qui
    n'est pas dans BE-088.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    instantane = await _charger_instantane_du_tenant(db, target_snapshot_id, tenant_id)

    if direction == DIRECTION_UPGRADE:
        raise billing_error(
            BillingErrorCode.INVALID_TRANSITION,
            "Le passage à une offre supérieure n'est pas encore disponible en cours de période.",
        )
    if abonnement.lifecycleStatus != CYCLE_DE_VIE_MODIFIABLE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    deja_planifie = await db.scalar(
        select(PlanChange.id).where(
            PlanChange.subscriptionId == abonnement.id,
            PlanChange.status == STATUT_PLANIFIE,
        )
    )
    if deja_planifie is not None:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    effective_at: datetime = abonnement.endDate
    demande = PlanChange(
        subscriptionId=abonnement.id,
        targetPlanVersionSnapshotId=instantane.id,
        direction=direction,
        effectiveAt=effective_at,
        status=STATUT_PLANIFIE,
        previewJson={
            "direction": direction,
            "targetPlanRef": instantane.planRef,
            "targetPlanVersion": instantane.planVersion,
            "effectiveAt": effective_at.isoformat(),
        },
    )
    db.add(demande)
    try:
        await db.commit()
    except IntegrityError:
        # Index unique partiel : une autre demande planifiée a été écrite entre-temps.
        await db.rollback()
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    await db.refresh(demande)
    return demande
