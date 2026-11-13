"""Service de clôture d'abonnement (BE-097).

Ce module est la seule porte d'écriture de la clôture. Il réutilise, sans les redéfinir :
- `charger_abonnement_du_tenant` et `TRANSITIONS_CYCLE_DE_VIE` (app/billing/subscriptions/etats.py) ;
- `demander_synchronisation` (app/billing/entitlement_sync/service.py, BE-085) pour demander à
  PH-09 la fin des droits ; PH-09 reste la seule autorité, la clôture ne touche à aucun droit ;
- `record_audit_entry` (app/billing/audit.py, BE-073) pour l'entrée d'audit de la clôture.

Décisions appliquées (écarts consignés) :
- Prérequis « données » : NON DÉFINI (QE-FAC-25). Recommandation appliquée : une demande
  d'export du payeur dont le statut n'est pas `ready` bloque la clôture ; aucune n'est
  présente aujourd'hui, donc le prérequis est satisfait par défaut.
- Prérequis « cas support » : BE-096 n'est pas implémenté ; aucun cas n'est lu, donc aucun
  cas ne bloque (CA-2).
- Permission : `billing.subscription.manage`, comme la résiliation (BE-090), contrôlée par la route.

Le commit de `demander_synchronisation` précède les écritures de la clôture : la demande
PH-09 est créée même si la clôture reste bloquée, ce qui est voulu.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.entitlement_sync.service import STATUT_APPLIQUEE, STATUT_DEMANDEE, STATUT_NOUVELLE_TENTATIVE, demander_synchronisation
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import CloseOperation, DataExportRequest, EntitlementSync, Invoice, PaymentAttempt, Subscription
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.errors import AppError

ETATS_CLOTURABLES = frozenset({"cancelled", "expired", "close_pending"})
STATUT_CLOTURE_TERMINEE = "completed"
STATUT_CLOTURE_PENDING_FINANCE = "close_pending_finance"
STATUT_CLOTURE_PENDING_DROITS = "close_pending_entitlement"
STATUT_CLOTURE_PENDING_DONNEES = "close_pending_data"
STATUT_PAIEMENT_INCONNU = "unknown"
STATUT_EXPORT_PRODUIT = "ready"
ACTION_AUDIT_CLOTURE = "billing.subscription.close"


async def demander_cloture(
    db: AsyncSession, subscription_id: uuid.UUID, tenant_id: uuid.UUID, actor_id: uuid.UUID
) -> CloseOperation:
    """Demande (ou reprend) la clôture de l'abonnement et renvoie la clôture.

    - Un abonnement hors tenant ou inexistant : `subscription_not_found` (404), sans fuite d'existence.
    - Une clôture déjà `completed` est renvoyée telle quelle (rejeu idempotent, aucune écriture).
    - Un état de cycle de vie non clôturable : `INVALID_TRANSITION` (409), rien n'est écrit.
    - Sinon, les trois prérequis sont évalués ; le premier manquant fixe le statut `close_pending_*`.
      Tous satisfaits : statut `completed`, lifecycle `subscription_closed`, entrée d'audit.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    terminee = await db.scalar(
        select(CloseOperation).where(
            CloseOperation.subscriptionId == abonnement.id,
            CloseOperation.status == STATUT_CLOTURE_TERMINEE,
        )
    )
    if terminee is not None:
        return terminee

    if abonnement.lifecycleStatus not in ETATS_CLOTURABLES:
        await db.rollback()
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    # La demande PH-09 (BE-085) commit elle-même : elle est faite avant toute écriture de la clôture.
    if not await _droits_confirmes(db, abonnement):
        if not await _synchronisation_en_cours(db, abonnement):
            await demander_synchronisation(db, tenant_id=tenant_id, subscription_id=abonnement.id)
            await db.refresh(abonnement)

    operation = await db.scalar(
        select(CloseOperation)
        .where(CloseOperation.subscriptionId == abonnement.id)
        .order_by(CloseOperation.requestedAt.desc())
        .limit(1)
        .with_for_update()
    )
    if operation is None:
        operation = CloseOperation(subscriptionId=abonnement.id, status="requested", prerequisitesJson={})
        db.add(operation)

    # `cancelled` ou `expired` passent à `close_pending` ; `close_pending` (reprise) reste tel quel.
    if abonnement.lifecycleStatus != "close_pending":
        abonnement.lifecycleStatus = "close_pending"
        abonnement.version += 1

    finance = await _prerequis_finance(db, abonnement)
    droits = await _prerequis_droits(db, abonnement)
    donnees = await _prerequis_donnees(db, abonnement, tenant_id)
    operation.prerequisitesJson = {"finance": finance, "entitlement": droits, "data": donnees}

    if not finance["satisfait"]:
        operation.status = STATUT_CLOTURE_PENDING_FINANCE
    elif not droits["satisfait"]:
        operation.status = STATUT_CLOTURE_PENDING_DROITS
    elif not donnees["satisfait"]:
        operation.status = STATUT_CLOTURE_PENDING_DONNEES
    else:
        operation.status = STATUT_CLOTURE_TERMINEE
        avant = {"lifecycleStatus": "close_pending", "version": abonnement.version}
        abonnement.lifecycleStatus = "subscription_closed"
        abonnement.version += 1
        apres = {"lifecycleStatus": "subscription_closed", "version": abonnement.version}
        await record_audit_entry(
            db,
            tenant_id,
            actor_id,
            action=ACTION_AUDIT_CLOTURE,
            scope="tenant",
            target_type="Subscription",
            target_id=abonnement.id,
            before_json=avant,
            after_json=apres,
        )

    await db.commit()
    await db.refresh(operation)
    return operation


async def _droits_confirmes(db: AsyncSession, abonnement: Subscription) -> bool:
    """Vrai si la dernière demande de synchronisation de l'abonnement est `applied`."""
    derniere = await db.scalar(
        select(EntitlementSync)
        .where(EntitlementSync.subscriptionId == abonnement.id)
        .order_by(EntitlementSync.requestedAt.desc())
        .limit(1)
    )
    return derniere is not None and derniere.status == STATUT_APPLIQUEE


async def _synchronisation_en_cours(db: AsyncSession, abonnement: Subscription) -> bool:
    """Vrai si une demande PH-09 est en attente : pas de doublon à créer."""
    derniere = await db.scalar(
        select(EntitlementSync)
        .where(EntitlementSync.subscriptionId == abonnement.id)
        .order_by(EntitlementSync.requestedAt.desc())
        .limit(1)
    )
    return derniere is not None and derniere.status in (STATUT_DEMANDEE, STATUT_NOUVELLE_TENTATIVE)


async def _prerequis_finance(db: AsyncSession, abonnement: Subscription) -> dict:
    """Finance : état financier connu et aucun paiement de l'abonnement dont l'issue est inconnue."""
    inconnus = await db.scalar(
        select(PaymentAttempt.id)
        .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
        .where(Invoice.subscriptionId == abonnement.id, PaymentAttempt.status == STATUT_PAIEMENT_INCONNU)
        .limit(1)
    )
    if inconnus is not None or abonnement.financialStatus == "pending":
        return {"satisfait": False, "motif": "FINANCE_RESULT_PENDING"}
    return {"satisfait": True}


async def _prerequis_droits(db: AsyncSession, abonnement: Subscription) -> dict:
    """Droits : fin d'entitlement acquittée par PH-09 (dernière synchronisation `applied`)."""
    if await _droits_confirmes(db, abonnement):
        return {"satisfait": True}
    return {"satisfait": False, "motif": "ENTITLEMENT_SYNC_PENDING"}


async def _prerequis_donnees(db: AsyncSession, abonnement: Subscription, tenant_id: uuid.UUID) -> dict:
    """Données : aucune demande d'export du payeur non produite (voir l'en-tête du module)."""
    if abonnement.payerId is None:
        return {"satisfait": True}
    non_produite = await db.scalar(
        select(DataExportRequest.id).where(
            DataExportRequest.accountId == abonnement.payerId,
            DataExportRequest.organizationId == tenant_id,
            DataExportRequest.status != STATUT_EXPORT_PRODUIT,
        ).limit(1)
    )
    if non_produite is not None:
        return {"satisfait": False, "motif": "EXPORT_NOT_READY"}
    return {"satisfait": True}
