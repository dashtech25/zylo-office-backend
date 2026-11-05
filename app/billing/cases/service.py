"""Service des cas de facturation et d'assistance (BE-096).

Seule porte d'écriture des cas (`billing_case`). Il réutilise :
- `record_audit_entry` (app/billing/audit.py, BE-073) : toute ouverture et toute résolution
  écrivent exactement une entrée d'audit, dans la même transaction que le cas ;
- `billing_error` et `BillingErrorCode` (app/billing/errors.py) pour les refus du catalogue.

Décisions appliquées (écarts consignés) :
- Colonnes NON DÉFINIES (QE-FAC-04) : `organizationId` (isolation tenant, CA-4), `resolutionReason`
  et `resolvedAt` (motif et date de résolution, CA-2). Recommandation appliquée : colonnes
  ajoutées, pas de table annexe.
- Approbation indépendante (QE-FAC-09) : un cas `action_pending` est une action sensible ; sa
  résolution exige un approbateur membre du tenant, distinct de l'acteur, sinon
  `APPROVAL_REQUIRED`. Les autres cas se résolvent sur la seule permission
  `billing.case.resolve`. Même règle que le remboursement (app/billing/refunds/service.py).
- Les cas ne sont jamais lus ni modifiés par la clôture d'abonnement (BE-097) : pas de cascade.

Le motif est obligatoire et non vide : il est validé par le schéma de la route (422) et
rappelé ici par `_motif_obligatoire` pour que le service seul ne puisse pas écrire un cas sans motif.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import BillingCase
from app.core.errors import AppError
from app.identity.models import OrganizationUser

STATUT_OUVERT = "open"
STATUT_RESOLU = "resolved"
ETATS_RESOLUBLES = frozenset({"open", "assigned", "investigating", "action_pending", "escalated"})
ETAT_ACTION_SENSIBLE = "action_pending"
ACTION_AUDIT_OUVERTURE = "billing.case.open"
ACTION_AUDIT_RESOLUTION = "billing.case.resolve"
TYPE_CIBLE = "BillingCase"


def _motif_obligatoire(motif: str) -> str:
    """Renvoie le motif nettoyé ; un motif vide ou blanc lève `ValueError` (jamais écrit)."""
    nettoye = (motif or "").strip()
    if not nettoye:
        raise ValueError("Le motif est obligatoire.")
    return nettoye


async def _est_membre(db: AsyncSession, tenant_id: uuid.UUID, utilisateur_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur est membre du tenant (approbateur d'une action sensible)."""
    lien = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == tenant_id,
            OrganizationUser.userId == utilisateur_id,
        )
    )
    return lien is not None


async def ouvrir_cas(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    acteur_id: uuid.UUID,
    *,
    scope: str,
    subject_ref: str,
    reason: str,
) -> BillingCase:
    """Ouvre un cas `open` dans le tenant, avec une entrée d'audit `billing.case.open`.

    Le tenant vient de l'en-tête (jamais du corps) ; l'acteur vient du jeton. Un champ d'assignation
    ou d'acteur envoyé dans le corps n'est jamais lu.
    """
    motif = _motif_obligatoire(reason)
    cas = BillingCase(
        organizationId=tenant_id,
        scope=scope,
        subjectRef=subject_ref,
        status=STATUT_OUVERT,
        reason=motif,
        openedAt=datetime.now(timezone.utc),
    )
    db.add(cas)
    await db.flush()
    await record_audit_entry(
        db,
        tenant_id,
        acteur_id,
        action=ACTION_AUDIT_OUVERTURE,
        scope="tenant",
        target_type=TYPE_CIBLE,
        target_id=cas.id,
        before_json=None,
        after_json={"status": STATUT_OUVERT},
        reason=motif,
    )
    await db.commit()
    return cas


async def resoudre_cas(
    db: AsyncSession,
    case_id: uuid.UUID,
    tenant_id: uuid.UUID,
    acteur_id: uuid.UUID,
    *,
    reason: str,
    approver_id: uuid.UUID | None,
) -> BillingCase:
    """Résout un cas du tenant avec motif et entrée d'audit `billing.case.resolve` (CA-2).

    - Cas absent ou d'un autre tenant : `case_not_found` (404), sans fuite d'existence (CA-4).
    - Statut hors `ETATS_RESOLUBLES` (déjà `resolved` ou `closed`) : `INVALID_TRANSITION` (409).
    - Statut `action_pending` : approbateur membre du tenant et distinct de l'acteur, sinon
      `APPROVAL_REQUIRED` (409) et rien n'est écrit.
    """
    motif = _motif_obligatoire(reason)
    cas = await db.scalar(
        select(BillingCase)
        .where(BillingCase.id == case_id, BillingCase.organizationId == tenant_id)
        .with_for_update()
    )
    if cas is None:
        raise AppError(code="case_not_found", message="Cas introuvable.", status_code=404)

    if cas.status not in ETATS_RESOLUBLES:
        await db.rollback()
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    if cas.status == ETAT_ACTION_SENSIBLE:
        approbation_valide = (
            approver_id is not None
            and approver_id != acteur_id
            and await _est_membre(db, tenant_id, approver_id)
        )
        if not approbation_valide:
            await db.rollback()
            raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)

    avant = {"status": cas.status}
    cas.status = STATUT_RESOLU
    cas.resolutionReason = motif
    cas.resolvedAt = datetime.now(timezone.utc)
    apres = {"status": cas.status}
    await record_audit_entry(
        db,
        tenant_id,
        acteur_id,
        action=ACTION_AUDIT_RESOLUTION,
        scope="tenant",
        target_type=TYPE_CIBLE,
        target_id=cas.id,
        before_json=avant,
        after_json=apres,
        reason=motif,
        approver_id=approver_id,
    )
    await db.commit()
    return cas
