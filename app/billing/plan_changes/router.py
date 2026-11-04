"""Routes de changement de plan d'abonnement (BE-088).

Routes, montées sous `/billing` (app/api/v1/router.py) :
- `POST /subscriptions/{subscriptionId}/plan-change/preview` : aperçu, lecture seule ;
- `POST /subscriptions/{subscriptionId}/plan-change` : application (downgrade planifié).

Corps commun : `targetPlanVersionSnapshotId` (UUID de l'instantané cible, BE-075) et
`direction` (`upgrade` ou `downgrade`, valeur contrôlée par le schéma).

Contrat :
- Le tenant courant vient de `X-Organization-Id` (`get_current_organization_id`).
- Permission : `billing.subscription.manage`. Sans elle : 403 `FORBIDDEN`, avant tout
  accès à l'abonnement, donc sans sonder son existence. Aucune écriture dans ce cas.
- Abonnement hors tenant ou inexistant : 404 `subscription_not_found`.
- Le périmètre payeur (ACTF-04, QE-FAC-03) n'est pas ouvert ici.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.plan_changes.service import appliquer_changement_plan, apercu_changement_plan
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class ChangementPlanRequete(BaseModel):
    """Corps commun à l'aperçu et à l'application."""

    targetPlanVersionSnapshotId: uuid.UUID
    direction: Literal["upgrade", "downgrade"]


class EffetsFinanciers(BaseModel):
    """Effets financiers d'un upgrade. `prorata` reste nul tant que QE-FAC-05 n'est pas tranché."""

    prorata: None = None
    prorataStatus: str
    resolvedPrice: dict | None = None
    priceErrorCode: str | None = None


class ApercuChangementPlanReponse(BaseModel):
    """Aperçu : effet à l'échéance pour un downgrade, effets financiers pour un upgrade."""

    subscriptionId: uuid.UUID
    direction: str
    targetPlanRef: str
    targetPlanVersion: int
    effectiveAt: datetime | None = None
    financialEffects: EffetsFinanciers | None = None


class DemandeChangementPlanReponse(BaseModel):
    """Demande de changement de plan créée (BE-088)."""

    id: uuid.UUID
    subscriptionId: uuid.UUID
    targetPlanVersionSnapshotId: uuid.UUID
    direction: str
    effectiveAt: datetime
    status: str


async def _verifier_permission(db: AsyncSession, current_user: User, organization_id: uuid.UUID) -> None:
    """Refuse en 403 `FORBIDDEN` sans la permission de gestion de l'abonnement."""
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)


@router.post(
    "/subscriptions/{subscription_id}/plan-change/preview",
    response_model=ApercuChangementPlanReponse,
    summary="Aperçu d'un changement de plan, sans écriture (BE-088)",
)
async def apercu(
    subscription_id: uuid.UUID,
    requete: ChangementPlanRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApercuChangementPlanReponse:
    """Renvoie l'aperçu. Refus : 403 `FORBIDDEN` ; 404 `subscription_not_found` ou `snapshot_not_found`."""
    await _verifier_permission(db, current_user, organization_id)
    resultat = await apercu_changement_plan(
        db,
        subscription_id,
        organization_id,
        target_snapshot_id=requete.targetPlanVersionSnapshotId,
        direction=requete.direction,
    )
    return ApercuChangementPlanReponse.model_validate(resultat)


@router.post(
    "/subscriptions/{subscription_id}/plan-change",
    response_model=DemandeChangementPlanReponse,
    summary="Appliquer un changement de plan : downgrade planifié à échéance (BE-088)",
)
async def appliquer(
    subscription_id: uuid.UUID,
    requete: ChangementPlanRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DemandeChangementPlanReponse:
    """Crée la demande `scheduled`. Refus : 403 `FORBIDDEN` ; 404 ; 409 `INVALID_TRANSITION`
    pour un upgrade (QE-FAC-05), un cycle de vie non actif, ou une demande déjà planifiée."""
    await _verifier_permission(db, current_user, organization_id)
    demande = await appliquer_changement_plan(
        db,
        subscription_id,
        organization_id,
        target_snapshot_id=requete.targetPlanVersionSnapshotId,
        direction=requete.direction,
    )
    return DemandeChangementPlanReponse(
        id=demande.id,
        subscriptionId=demande.subscriptionId,
        targetPlanVersionSnapshotId=demande.targetPlanVersionSnapshotId,
        direction=demande.direction,
        effectiveAt=demande.effectiveAt,
        status=demande.status,
    )
