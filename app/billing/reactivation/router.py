"""Route de réactivation d'abonnement (BE-092).

Route : `POST /api/v1/billing/subscriptions/{subscriptionId}/reactivate`, montée sous `/billing`
(app/api/v1/router.py).

Corps : `paymentAttemptId` (obligatoire), identifiant de la tentative de paiement confirmée qui
rattache le paiement à l'abonnement. Sans lui, la requête est refusée en validation (422).

Contrat :
- Le tenant courant vient de l'en-tête `X-Organization-Id` (`get_current_organization_id`).
- Permission : `billing.subscription.manage`. Sans elle : 403 `FORBIDDEN`, abonnement inchangé.
  Le contrôle précède le périmètre, comme pour la résiliation (BE-090).
- Abonnement hors tenant ou inexistant : 404 `subscription_not_found`.
- Paiement non confirmé : 402 `PAYMENT_DECLINED` ; issue inconnue : `RECONCILIATION_REQUIRED`.
- Clos ou non réactivable : 409 `INVALID_TRANSITION`.
- Succès : 200 avec l'agrégat abonnement (SubscriptionEtatResponse de BE-079), complété de
  `cancelMode` et `cancelEffectiveAt` comme la réponse de BE-090.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.reactivation.service import reactiver_abonnement
from app.billing.subscriptions.router import SubscriptionEtatResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class ReactivationRequete(BaseModel):
    """Corps de la demande de réactivation : la tentative de paiement confirmée."""

    paymentAttemptId: uuid.UUID


class ReactivationReponse(SubscriptionEtatResponse):
    """Agrégat abonnement après réactivation (BE-092)."""

    cancelMode: str | None = None
    cancelEffectiveAt: datetime | None = None


@router.post(
    "/subscriptions/{subscription_id}/reactivate",
    response_model=ReactivationReponse,
    summary="Réactiver un abonnement après incident ou résiliation (BE-092)",
)
async def reactiver(
    subscription_id: uuid.UUID,
    requete: ReactivationRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReactivationReponse:
    """Réactive l'abonnement si un paiement confirmé le justifie ; voir les refus dans le module."""
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    abonnement = await reactiver_abonnement(
        db,
        subscription_id,
        organization_id,
        payment_attempt_id=requete.paymentAttemptId,
    )
    return ReactivationReponse.model_validate(abonnement)
