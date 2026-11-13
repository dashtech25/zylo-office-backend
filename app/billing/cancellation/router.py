"""Route de résiliation d'abonnement (BE-090).

Route : `POST /api/v1/billing/subscriptions/{subscriptionId}/cancel`, montée sous
`/billing` (app/api/v1/router.py).

Corps (optionnel) : `cancelMode` (`end_of_period` par défaut, `immediate` refusé) et
`reason` (motif, exigé par l'audit de BE-073).

Contrat :
- Le tenant courant vient de l'en-tête `X-Organization-Id` (`get_current_organization_id`).
- Permission : `billing.subscription.manage` (SUBSCRIPTION_MANAGE). Sans elle : 403
  `FORBIDDEN`, et l'abonnement n'est pas touché. Le contrôle précède le périmètre : un
  appelant sans permission ne peut pas sonder l'existence d'un abonnement.
- Abonnement hors tenant ou inexistant : 404 `subscription_not_found`, même réponse.
- Succès : 200 avec l'agrégat abonnement (SubscriptionEtatResponse de BE-079) complété
  de `cancelMode` et `cancelEffectiveAt`.

Le périmètre payeur (ACTF-04 acheteur, QE-FAC-03) n'est pas ouvert ici : seule la
permission de gestion sur le tenant bénéficiaire donne accès.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.cancellation.service import MODE_FIN_DE_PERIODE, resilier_abonnement
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.subscriptions.router import SubscriptionEtatResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class ResiliationRequete(BaseModel):
    """Corps de la demande de résiliation. `reason` est exigé par l'audit (BE-073)."""

    cancelMode: Literal["end_of_period", "immediate"] = MODE_FIN_DE_PERIODE
    reason: str | None = None


class ResiliationReponse(SubscriptionEtatResponse):
    """Agrégat abonnement après demande de résiliation (BE-090)."""

    cancelMode: str | None = None
    cancelEffectiveAt: datetime | None = None


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=ResiliationReponse,
    summary="Résilier un abonnement, à échéance (BE-090)",
)
async def resilier(
    subscription_id: uuid.UUID,
    requete: ResiliationRequete | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResiliationReponse:
    """Demande la résiliation ; par défaut à échéance, sans coupure avant la fin de période.

    Refus : 403 `FORBIDDEN` sans `billing.subscription.manage` ; 404 `subscription_not_found`
    hors tenant ; 409 `INVALID_TRANSITION` pour une résiliation immédiate ou une transition
    non permise ; `APPROVAL_REQUIRED` sans motif.
    """
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    corps = requete or ResiliationRequete()
    abonnement = await resilier_abonnement(
        db,
        subscription_id,
        organization_id,
        current_user.id,
        cancel_mode=corps.cancelMode,
        reason=corps.reason,
    )
    return ResiliationReponse.model_validate(abonnement)
