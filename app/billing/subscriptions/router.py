"""Routes du cycle de vie Subscription et commandes (BE-203 et BE-079).

Routes :
- GET /api/v1/billing/subscriptions/{subscription_id} (BE-079 : lecture)
- POST /api/v1/subscriptions (BE-203 : CreateSubscription)
- POST /api/v1/subscriptions/{subscription_id}/confirm (BE-203 : ConfirmSubscription)
- POST /api/v1/subscriptions/{subscription_id}/change-plan (BE-203)
- POST /api/v1/subscriptions/{subscription_id}/cancel (BE-203)
- POST /api/v1/subscriptions/{subscription_id}/expire (BE-203)
- POST /api/v1/subscriptions/{subscription_id}/close (BE-203 : CloseSubscription)

Contrat :
- Le tenant courant vient de l'en-tête `X-Organization-Id`.
- Permissions : `billing.subscription.read` (GET), `billing.operate` (POST).
- Abonnement d'un autre tenant, ou inexistant : 404 `subscription_not_found`.
- Transitions invalides : 422 avec code d'erreur.
- Chaque transition réussie écrit une entrée outbox et une entrée d'audit (BE-203 CA-7).
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_READ
from app.billing.subscriptions.etats import charger_abonnement_du_tenant, transition_etat
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission, require_permission

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
    status: str

    model_config = {"from_attributes": True}


class CreateSubscriptionRequest(BaseModel):
    """Demande de création d'abonnement (BE-203)."""

    planVersionId: uuid.UUID = Field(..., description="Version du plan")
    payerId: uuid.UUID = Field(..., description="Payeur de l'abonnement")
    beneficiaryIds: list[uuid.UUID] = Field(..., description="Bénéficiaires")
    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class ConfirmSubscriptionRequest(BaseModel):
    """Demande de confirmation d'abonnement (BE-203)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class ChangePlanRequest(BaseModel):
    """Demande de changement de plan (BE-203)."""

    newPlanVersionId: uuid.UUID = Field(..., description="Nouvelle version du plan")
    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class CancelSubscriptionRequest(BaseModel):
    """Demande d'annulation d'abonnement (BE-203)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")
    effectiveDate: str | None = Field(None, description="Date d'effet de l'annulation (défaut: fin de période)")


class ExpireSubscriptionRequest(BaseModel):
    """Demande d'expiration d'abonnement (BE-203)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class CloseSubscriptionRequest(BaseModel):
    """Demande de clôture d'abonnement (BE-203)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


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


@router.post(
    "/subscriptions",
    response_model=SubscriptionEtatResponse,
    summary="Créer un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def creer_abonnement(
    request: CreateSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Crée un nouvel abonnement.

    Require: `billing.operate` permission.
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant.
    """
    # TODO : implémenter la création d'abonnement avec idempotence
    raise AppError(code="not_implemented", message="CreateSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/confirm",
    response_model=SubscriptionEtatResponse,
    summary="Confirmer un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def confirmer_abonnement(
    subscription_id: uuid.UUID,
    request: ConfirmSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Confirme un abonnement en attente.

    Require: `billing.operate` permission.
    Transition: pending -> trialing ou pending -> active.
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant ; 422 si transition invalide.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # Vérifier que l'abonnement n'est pas en statut incomplete ou disputed
    if abonnement.status in ["incomplete", "disputed"]:
        raise AppError(code="invalid_state_for_action", message=f"Impossible de confirmer un abonnement en statut {abonnement.status}.", status_code=422)

    # TODO : implémenter la confirmation avec transition d'état
    raise AppError(code="not_implemented", message="ConfirmSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/change-plan",
    response_model=SubscriptionEtatResponse,
    summary="Changer le plan d'un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def changer_plan(
    subscription_id: uuid.UUID,
    request: ChangePlanRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Change le plan d'un abonnement actif.

    Require: `billing.operate` permission.
    Transition: active -> change_scheduled -> active.
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant ; 422 si transition invalide.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # Vérifier que le changement de plan est possible (pas en statut cancelled)
    if abonnement.status in ["cancelled", "subscription_closed"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible de changer le plan après annulation.", status_code=422)

    # TODO : implémenter le changement de plan
    raise AppError(code="not_implemented", message="ChangePlan non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionEtatResponse,
    summary="Annuler un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def annuler_abonnement(
    subscription_id: uuid.UUID,
    request: CancelSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Annule un abonnement.

    Require: `billing.operate` permission.
    Transition: active -> cancel_scheduled (par défaut à periodEnd).
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant ; 422 si transition invalide.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # Vérifier que l'annulation n'est pas sur un statut invalide
    if abonnement.status in ["incomplete", "disputed", "cancelled"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible d'annuler dans cet état.", status_code=422)

    # TODO : implémenter l'annulation avec date d'effet = periodEnd par défaut
    raise AppError(code="not_implemented", message="CancelSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/expire",
    response_model=SubscriptionEtatResponse,
    summary="Expirer un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def expirer_abonnement(
    subscription_id: uuid.UUID,
    request: ExpireSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Marque un abonnement comme expiré.

    Require: `billing.operate` permission.
    Transition: active/cancel_scheduled -> expired.
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant ; 422 si transition invalide.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # TODO : implémenter l'expiration
    raise AppError(code="not_implemented", message="ExpireSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/close",
    response_model=SubscriptionEtatResponse,
    summary="Clôturer un abonnement (BE-203)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def cloturer_abonnement(
    subscription_id: uuid.UUID,
    request: CloseSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Clôture un abonnement (passage à subscription_closed).

    Require: `billing.operate` permission.
    Transition: expired ou cancelled -> close_pending -> subscription_closed.
    Prérequis de clôture : finances réglées, pas de litiges en cours.
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant ; 422 si transition invalide ou prérequis manquants.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # Vérifier les prérequis de clôture
    if abonnement.financialStatus != "settled":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer sans finances réglées.", status_code=422)

    if abonnement.incidentStatus != "none":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer avec des incidents non résolus.", status_code=422)

    # TODO : implémenter la clôture
    raise AppError(code="not_implemented", message="CloseSubscription non encore implémenté.", status_code=501)
