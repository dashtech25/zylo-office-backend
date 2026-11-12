"""Routes du cycle de vie Subscription (BE-203) au niveau racine /api/v1/subscriptions.

Cet objectif est distinct du router.py (GET /api/v1/billing/subscriptions/{id}, BE-079).
Les routes de BE-203 sont à la racine pour refléter le contrat API spécifié dans
implementation-backend/tasks-donnees-api-contrats.md.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.permissions import SUBSCRIPTION_READ
from app.billing.subscriptions.etats import charger_abonnement_du_tenant, transition_etat
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission

router = APIRouter()


class SubscriptionLifecycleResponse(BaseModel):
    """Réponse d'une opération du cycle de vie (BE-203)."""

    id: uuid.UUID
    status: str
    lifecycleStatus: str
    financialStatus: str
    incidentStatus: str
    version: int

    model_config = {"from_attributes": True}


class CreateSubscriptionRequest(BaseModel):
    """Demande de création d'abonnement (BE-203 CA-1)."""

    planVersionId: uuid.UUID = Field(..., description="Version du plan")
    payerId: uuid.UUID = Field(..., description="Payeur de l'abonnement")
    beneficiaryIds: list[uuid.UUID] = Field(..., description="Bénéficiaires")
    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class ConfirmSubscriptionRequest(BaseModel):
    """Demande de confirmation d'abonnement (BE-203 CA-1)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class ChangePlanRequest(BaseModel):
    """Demande de changement de plan (BE-203 CA-1)."""

    newPlanVersionId: uuid.UUID = Field(..., description="Nouvelle version du plan")
    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class CancelSubscriptionRequest(BaseModel):
    """Demande d'annulation d'abonnement (BE-203 CA-3)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")
    effectiveDate: str | None = Field(None, description="Date d'effet de l'annulation (défaut: fin de période)")


class ExpireSubscriptionRequest(BaseModel):
    """Demande d'expiration d'abonnement (BE-203 CA-1)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


class CloseSubscriptionRequest(BaseModel):
    """Demande de clôture d'abonnement (BE-203 CA-4)."""

    idempotencyKey: str = Field(..., description="Clé d'idempotence")


@router.post(
    "/subscriptions",
    response_model=SubscriptionLifecycleResponse,
    summary="Créer un abonnement (BE-203 CA-5)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def creer_abonnement(
    request: CreateSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Crée un nouvel abonnement (BE-203 CA-5 : permission billing.operate requise).

    Contrat : idempotence assurée par `idempotencyKey` (BE-183).
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant.
    """
    raise AppError(code="not_implemented", message="CreateSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/confirm",
    response_model=SubscriptionLifecycleResponse,
    summary="Confirmer un abonnement (BE-203 CA-1)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def confirmer_abonnement(
    subscription_id: uuid.UUID,
    request: ConfirmSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Confirme un abonnement en attente (BE-203 CA-1, CA-2).

    Transitions : pending -> trialing/active (BE-203 CA-1).
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant (BE-203 CA-6) ;
    422 si transition invalide (CA-1) ou statut incomplete/disputed (CA-2).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-2 : les statuts `incomplete` et `disputed` ne sont pas transitionnables
    if abonnement.status in ["incomplete", "disputed"]:
        raise AppError(code="invalid_state_for_action", message=f"Impossible de confirmer en statut {abonnement.status}.", status_code=422)

    raise AppError(code="not_implemented", message="ConfirmSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/change-plan",
    response_model=SubscriptionLifecycleResponse,
    summary="Changer le plan d'un abonnement (BE-203 CA-1)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def changer_plan(
    subscription_id: uuid.UUID,
    request: ChangePlanRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Change le plan d'un abonnement actif (BE-203 CA-1).

    Refus : 403 si permission absente ; 404 si abonnement hors du tenant (BE-203 CA-6) ;
    422 si transition invalide (CA-1).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-1 : transition hors graphe renvoie 422
    if abonnement.status in ["cancelled", "subscription_closed"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible de changer le plan après annulation.", status_code=422)

    raise AppError(code="not_implemented", message="ChangePlan non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionLifecycleResponse,
    summary="Annuler un abonnement (BE-203 CA-1, CA-3)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def annuler_abonnement(
    subscription_id: uuid.UUID,
    request: CancelSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Annule un abonnement (BE-203 CA-3 : date d'effet = periodEnd par défaut).

    Refus : 403 si permission absente ; 404 si abonnement hors du tenant (CA-6) ;
    422 si transition invalide (CA-1).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-1 : transition hors graphe renvoie 422
    if abonnement.status in ["incomplete", "disputed", "cancelled"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible d'annuler dans cet état.", status_code=422)

    raise AppError(code="not_implemented", message="CancelSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/expire",
    response_model=SubscriptionLifecycleResponse,
    summary="Expirer un abonnement (BE-203 CA-1)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def expirer_abonnement(
    subscription_id: uuid.UUID,
    request: ExpireSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Marque un abonnement comme expiré (BE-203 CA-1).

    Refus : 403 si permission absente ; 404 si abonnement hors du tenant (CA-6) ;
    422 si transition invalide (CA-1).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    raise AppError(code="not_implemented", message="ExpireSubscription non encore implémenté.", status_code=501)


@router.post(
    "/subscriptions/{subscription_id}/close",
    response_model=SubscriptionLifecycleResponse,
    summary="Clôturer un abonnement (BE-203 CA-4)",
    dependencies=[Depends(require_permission("billing.operate"))],
)
async def cloturer_abonnement(
    subscription_id: uuid.UUID,
    request: CloseSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionLifecycleResponse:
    """Clôture un abonnement (BE-203 CA-4 : sans prérequis de clôture, refuse).

    Prérequis de clôture : finances réglées (financialStatus == settled), pas d'incidents (incidentStatus == none).
    Refus : 403 si permission absente ; 404 si abonnement hors du tenant (CA-6) ;
    422 si transition invalide (CA-1) ou prérequis manquants (CA-4).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-4 : `expire` ne fait pas passer à `subscription_closed` sans prérequis de clôture vérifiés
    if abonnement.financialStatus != "settled":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer sans finances réglées.", status_code=422)

    if abonnement.incidentStatus != "none":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer avec des incidents non résolus.", status_code=422)

    raise AppError(code="not_implemented", message="CloseSubscription non encore implémenté.", status_code=501)
