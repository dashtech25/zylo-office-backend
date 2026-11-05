"""Route de clôture d'abonnement (BE-097).

Route : `POST /api/v1/billing/subscriptions/{subscriptionId}/close`, montée sous `/billing`
(app/api/v1/router.py). Pas de corps.

Contrat :
- Le tenant courant vient de l'en-tête `X-Organization-Id` (`get_current_organization_id`).
- Permission : `billing.subscription.manage`. Sans elle : 403 `FORBIDDEN`, rien n'est touché.
  Le contrôle précède le périmètre : un appelant sans permission ne sonde pas l'existence.
- Abonnement hors tenant ou inexistant : 404 `subscription_not_found`, même réponse.
- Abonnement non clôturable (ni `cancelled`, ni `expired`, ni déjà en clôture) : 409 `INVALID_TRANSITION`.
- Succès : 200 avec la clôture ; `status` vaut `completed` si tous les prérequis sont
  satisfaits, sinon le `close_pending_*` du premier prérequis manquant.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.close.service import demander_cloture
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Subscription
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class ClotureReponse(BaseModel):
    """Clôture d'abonnement après demande (BE-097)."""

    id: uuid.UUID
    subscriptionId: uuid.UUID
    status: str
    prerequisitesJson: dict
    requestedAt: datetime
    lifecycleStatus: str


@router.post(
    "/subscriptions/{subscription_id}/close",
    response_model=ClotureReponse,
    summary="Demander la clôture d'un abonnement (BE-097)",
)
async def cloturer(
    subscription_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClotureReponse:
    """Demande la clôture ; rejouable tant qu'elle n'est pas `completed`, puis renvoie la même clôture."""
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    operation = await demander_cloture(db, subscription_id, organization_id, current_user.id)
    lifecycle = await db.scalar(select(Subscription.lifecycleStatus).where(Subscription.id == subscription_id))
    return ClotureReponse(
        id=operation.id,
        subscriptionId=operation.subscriptionId,
        status=operation.status,
        prerequisitesJson=operation.prerequisitesJson,
        requestedAt=operation.requestedAt,
        lifecycleStatus=lifecycle,
    )

