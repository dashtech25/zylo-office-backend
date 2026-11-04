"""Route de lecture de l'agrégat abonnement (BE-079).

Route : `GET /api/v1/billing/subscriptions/{subscriptionId}`, montée sous `/billing`
(app/api/v1/router.py).

Contrat :
- Le tenant courant vient de l'en-tête `X-Organization-Id`, validé par
  `get_current_organization_id` (appartenance active, sinon 404 `organization_not_found`).
- Permission : `billing.subscription.read` (SUBSCRIPTION_READ). Sans elle : 403 `FORBIDDEN`.
  Le contrôle est fait ici et non par `require_permission`, pour répondre au code
  `FORBIDDEN` du catalogue (app/billing/errors.py) et non à `permission_denied`.
- Abonnement d'un autre tenant, ou inexistant : 404 `subscription_not_found`, avec la même
  réponse dans les deux cas (CA-4).
- La réponse expose les trois axes séparément. Elle ne contient aucune donnée fournisseur
  de paiement, et aucun axe ne confère de droit (voir app/billing/subscriptions/etats.py).

Ordre des contrôles : appartenance au tenant, puis permission, puis périmètre. Un
appelant sans permission ne peut donc pas sonder l'existence d'un abonnement.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_READ
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class SubscriptionEtatResponse(BaseModel):
    """Agrégat abonnement : identité, rôles de périmètre et les trois axes séparés (BE-079)."""

    id: uuid.UUID
    planId: uuid.UUID
    organizationId: uuid.UUID
    beneficiaryTenantId: uuid.UUID | None = None
    payerId: uuid.UUID | None = None
    lifecycleStatus: str
    financialStatus: str
    incidentStatus: str
    version: int

    model_config = {"from_attributes": True}


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionEtatResponse,
    summary="Lire un abonnement et ses trois axes d'état (BE-079)",
)
async def lire_abonnement(
    subscription_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Renvoie l'abonnement si le tenant courant en est le bénéficiaire et si la permission est accordée.

    Refus : 403 `FORBIDDEN` sans `billing.subscription.read` ; 404 `subscription_not_found`
    pour un abonnement hors du tenant ou inexistant.
    """
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    return SubscriptionEtatResponse.model_validate(abonnement)
