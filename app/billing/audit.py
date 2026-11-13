"""Journal d'audit des gestes financiers et sensibles de la facturation (BE-073).

Ce module ne crée aucune table : il écrit dans `audit_event`, la table unique du
journal (BE-007, décision D2), via `app.audit.service.record_audit_event`. Il
ajoute trois garanties propres à la facturation :

1. Un geste sensible (`GESTES_SENSIBLES`) doit porter un motif non vide, sinon
   `APPROVAL_REQUIRED` est levé et rien n'est écrit (CA-4).
2. Chaque geste écrit exactement une entrée, avec l'état avant et l'état après
   (`changes = {"before": ..., "after": ...}`) (CA-1).
3. Les entrées `billing.*` ne peuvent plus être modifiées ni supprimées : une
   migration pose un trigger PostgreSQL qui refuse UPDATE et DELETE (CA-2). Le
   service ne fournit d'ailleurs aucune fonction de modification.

Correspondance des champs demandés par BE-073 avec les colonnes de `audit_event`
(correspondance NON DÉFINIE dans la définition, QE-FAC-04 et QE-FAC-13 ; choix
appliqué ici) :
- `actorId`        -> `actorUserId`
- `scope`          -> `scopeResourceType` (valeurs : `payeur`, `tenant`, `beneficiaire`)
- `action`         -> `action`
- `targetType`     -> `entityType`
- `targetId`       -> `entityId`
- `beforeJson` / `afterJson` -> `changes` (clés `before` et `after`)
- `reason`         -> `reason`
- `approverId`     -> `approvalId`
- `result`         -> `result` (`success`, `refused`, `error`)
- `occurredAt`     -> `createdAt` (horodatage serveur, à l'écriture)

Un appelant écrit dans sa propre transaction : ce module ne fait jamais `commit()`,
pour qu'une entrée d'audit ne survive jamais à une action qui a échoué.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.service import record_audit_event
from app.billing.errors import BillingErrorCode, billing_error
from app.core.errors import AppError

# Gestes dont l'entrée exige un motif (CA-4). Liste fixée par BE-073 : approbation
# de remboursement, changement de plan, résiliation, finalisation de facture.
GESTES_SENSIBLES = frozenset({
    "billing.refund.approve",
    "billing.plan.change",
    "billing.subscription.terminate",
    "billing.invoice.finalize",
    "billing.credit_note.issue",
})

# Périmètres d'une entrée : payeur, tenant bénéficiaire, bénéficiaire (BE-071).
PERIMETRES_AUDIT_FACTURATION = ("payeur", "tenant", "beneficiaire")

PREFIXE_AUDIT_FACTURATION = "billing."


async def record_audit_entry(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    action: str,
    scope: str,
    target_type: str,
    target_id: uuid.UUID | None,
    before_json: dict[str, Any] | None,
    after_json: dict[str, Any] | None,
    summary: str | None = None,
    reason: str | None = None,
    approver_id: uuid.UUID | str | None = None,
    result: str = "success",
) -> AuditEvent:
    """Écrit exactement une entrée d'audit pour un geste de facturation.

    Paramètres :
    - `organization_id` : organisation dans laquelle l'entrée est rangée (isolation, CA-3) ;
    - `actor_id` : utilisateur qui a fait le geste ;
    - `action` : code du geste, préfixé `billing.` ; un code de `GESTES_SENSIBLES`
      exige un motif ;
    - `scope` : `payeur`, `tenant` ou `beneficiaire` (`PERIMETRES_AUDIT_FACTURATION`) ;
    - `target_type` / `target_id` : objet touché (ex. `Subscription`, son identifiant) ;
    - `before_json` / `after_json` : états avant et après, sans secret (masquage
      assuré par le service d'audit) ; `None` pour une création ou une suppression ;
    - `summary` : texte lisible pré-rendu ; à défaut, un texte est construit à partir
      de l'action et de la cible ;
    - `reason` : motif. Obligatoire pour un geste sensible ; ignoré sinon ;
    - `approver_id` : utilisateur qui a approuvé, s'il y en a un ;
    - `result` : `success`, `refused` ou `error`.

    Erreurs :
    - `APPROVAL_REQUIRED` (`billing_error`) si le geste est sensible et que le motif
      est absent, vide ou composé d'espaces. Rien n'est écrit dans ce cas ;
    - `AppError` `audit_invalid_write` si le périmètre est inconnu, ou si le service
      d'audit refuse l'écriture (organisation ou acteur absent, résultat inconnu).

    Retourne l'entrée ajoutée à la session (non encore validée : l'appelant commit).
    """
    if not action.startswith(PREFIXE_AUDIT_FACTURATION):
        raise AppError(
            code="audit_invalid_write",
            message=f"Geste d'audit facturation hors préfixe 'billing.' : {action!r}.",
            status_code=500,
        )
    if scope not in PERIMETRES_AUDIT_FACTURATION:
        raise AppError(
            code="audit_invalid_write",
            message=f"Périmètre d'audit inconnu : {scope!r}.",
            status_code=500,
        )

    motif = reason.strip() if reason else None
    if action in GESTES_SENSIBLES and not motif:
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED, "Un motif est requis pour ce geste sensible.")

    texte = summary or f"{action} sur {target_type} {target_id or ''}".strip()
    return await record_audit_event(
        db,
        organization_id,
        actor_id,
        action=action,
        entity_type=target_type,
        entity_id=target_id,
        summary=texte,
        changes={"before": before_json, "after": after_json},
        scope_resource_type=scope,
        result=result,
        reason=motif,
        approval_id=str(approver_id) if approver_id is not None else None,
    )
