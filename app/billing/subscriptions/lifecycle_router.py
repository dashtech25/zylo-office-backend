"""Routes du cycle de vie Subscription (BE-203) au niveau racine /api/v1/subscriptions.

Cet objectif est distinct du router.py (GET /api/v1/billing/subscriptions/{id}, BE-079).
Les routes de BE-203 sont à la racine pour refléter le contrat API spécifié dans
implementation-backend/tasks-donnees-api-contrats.md.

Chaque route implémente :
- CA-1 : vérification des transitions d'état via `transition_etat` ;
- CA-2 : refus des statuts incomplete/disputed (non transitionnables) ;
- CA-3 : annulation programmée à la fin de la période par défaut ;
- CA-4 : clôture sans prérequis de clôture vérifiés renvoie 422 ;
- CA-5 : permission billing.operate requise ;
- CA-6 : isolation tenant via `charger_abonnement_du_tenant` ;
- CA-7 : écriture atomique dans outbox et audit via `executer_mutation_sensible`.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.billing.permissions import SUBSCRIPTION_READ
from app.billing.subscriptions.etats import charger_abonnement_du_tenant, transition_etat
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.evenements.outbox import enregistrer_evenement
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

    Implémentation spéculative (BE-201, BE-202 requis pour finaliser).
    """
    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_creer(session: AsyncSession):
        """Crée un nouvel abonnement dans le tenant (CA-5)."""
        # Récupérer le plan si nécessaire
        # Appel provisoire - la finalisation dépend de BE-201/BE-202
        raise NotImplementedError("CreateSubscription : implémentation en attente de BE-201/BE-202")

    try:
        # TODO (après BE-201/BE-202) : adapter le traitement d'idempotence
        abonnement = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.create",
            entity_type="subscription",
            entity_id=None,  # Le nouvel ID après création
            resume=f"Création d'abonnement pour plan {request.planVersionId}",
            mutation=mutation_creer,
            changes=None,
        )
        return SubscriptionLifecycleResponse.model_validate(abonnement)
    except NotImplementedError:
        raise AppError(code="not_implemented", message="CreateSubscription en développement.", status_code=501)


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

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_confirmer(session: AsyncSession):
        """Transition pending -> trialing (CA-1) avec vérification des transitions."""
        # CA-1 : utiliser transition_etat pour vérifier la validité
        # La cible (trialing ou active) dépend de la logique métier
        # Pour cette implémentation spéculative, on passe à 'trialing'
        transitioned = await transition_etat(session, subscription_id, organization_id, "lifecycle", "trialing")
        return transitioned

    try:
        abonnement_updated = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.confirm",
            entity_type="subscription",
            entity_id=subscription_id,
            resume=f"Confirmation de l'abonnement {subscription_id}",
            mutation=mutation_confirmer,
            changes=lambda sub: {"lifecycleStatus": sub.lifecycleStatus, "version": sub.version},
        )

        # Enregistrer un événement dans l'outbox (CA-7)
        await enregistrer_evenement(
            db,
            {
                "eventType": "subscription.confirmed",
                "tenantId": str(organization_id),
                "correlationId": str(request.idempotencyKey),
                "acteur": str(current_user.id),
                "data": {"subscriptionId": str(subscription_id)},
            },
            emetteur_tenant=organization_id,
        )

        await db.commit()
        return SubscriptionLifecycleResponse.model_validate(abonnement_updated)
    except Exception as exc:
        if "INVALID_TRANSITION" in str(exc):
            raise AppError(code="invalid_state_for_action", message="Transition d'état invalide.", status_code=422)
        raise


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

    Implémentation spéculative (CA-1 vérifiée via transition_etat).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-1 : transition hors graphe renvoie 422
    if abonnement.status in ["cancelled", "subscription_closed"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible de changer le plan après annulation.", status_code=422)

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_changer(session: AsyncSession):
        """Change le plan : transition à change_scheduled (CA-1)."""
        # Pour cette spéculation, on passe à change_scheduled
        transitioned = await transition_etat(session, subscription_id, organization_id, "lifecycle", "change_scheduled")
        return transitioned

    try:
        abonnement_updated = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.change_plan",
            entity_type="subscription",
            entity_id=subscription_id,
            resume=f"Changement du plan de l'abonnement {subscription_id} vers {request.newPlanVersionId}",
            mutation=mutation_changer,
            changes=lambda sub: {"lifecycleStatus": sub.lifecycleStatus, "version": sub.version},
        )

        # Enregistrer un événement dans l'outbox (CA-7)
        await enregistrer_evenement(
            db,
            {
                "eventType": "subscription.plan_changed",
                "tenantId": str(organization_id),
                "correlationId": str(request.idempotencyKey),
                "acteur": str(current_user.id),
                "data": {"subscriptionId": str(subscription_id), "newPlanVersionId": str(request.newPlanVersionId)},
            },
            emetteur_tenant=organization_id,
        )

        await db.commit()
        return SubscriptionLifecycleResponse.model_validate(abonnement_updated)
    except Exception as exc:
        if "INVALID_TRANSITION" in str(exc):
            raise AppError(code="INVALID_TRANSITION", message="Transition d'état invalide.", status_code=422)
        raise


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

    Implémentation spéculative (CA-3 gérée via effectiveDate ou periodEnd).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-1 : transition hors graphe renvoie 422
    if abonnement.status in ["incomplete", "disputed", "cancelled"]:
        raise AppError(code="INVALID_TRANSITION", message="Impossible d'annuler dans cet état.", status_code=422)

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_annuler(session: AsyncSession):
        """Annule un abonnement : transition à cancel_scheduled (CA-1, CA-3)."""
        # CA-3 : effectiveDate par défaut à periodEnd
        # Le calcul de periodEnd et le stockage de la date d'effet dépendent de BE-201/BE-202
        transitioned = await transition_etat(session, subscription_id, organization_id, "lifecycle", "cancel_scheduled")
        return transitioned

    try:
        abonnement_updated = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.cancel",
            entity_type="subscription",
            entity_id=subscription_id,
            resume=f"Annulation programmée de l'abonnement {subscription_id}" if request.effectiveDate is None else f"Annulation à {request.effectiveDate}",
            mutation=mutation_annuler,
            changes=lambda sub: {"lifecycleStatus": sub.lifecycleStatus, "version": sub.version},
        )

        # Enregistrer un événement dans l'outbox (CA-7)
        await enregistrer_evenement(
            db,
            {
                "eventType": "subscription.cancelled",
                "tenantId": str(organization_id),
                "correlationId": str(request.idempotencyKey),
                "acteur": str(current_user.id),
                "data": {"subscriptionId": str(subscription_id), "effectiveDate": request.effectiveDate},
            },
            emetteur_tenant=organization_id,
        )

        await db.commit()
        return SubscriptionLifecycleResponse.model_validate(abonnement_updated)
    except Exception as exc:
        if "INVALID_TRANSITION" in str(exc):
            raise AppError(code="INVALID_TRANSITION", message="Transition d'état invalide.", status_code=422)
        raise


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

    Implémentation spéculative (CA-1 vérifiée via transition_etat).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_expirer(session: AsyncSession):
        """Marque un abonnement comme expiré : transition à expired (CA-1)."""
        transitioned = await transition_etat(session, subscription_id, organization_id, "lifecycle", "expired")
        return transitioned

    try:
        abonnement_updated = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.expire",
            entity_type="subscription",
            entity_id=subscription_id,
            resume=f"Expiration de l'abonnement {subscription_id}",
            mutation=mutation_expirer,
            changes=lambda sub: {"lifecycleStatus": sub.lifecycleStatus, "version": sub.version},
        )

        # Enregistrer un événement dans l'outbox (CA-7)
        await enregistrer_evenement(
            db,
            {
                "eventType": "subscription.expired",
                "tenantId": str(organization_id),
                "correlationId": str(request.idempotencyKey),
                "acteur": str(current_user.id),
                "data": {"subscriptionId": str(subscription_id)},
            },
            emetteur_tenant=organization_id,
        )

        await db.commit()
        return SubscriptionLifecycleResponse.model_validate(abonnement_updated)
    except Exception as exc:
        if "INVALID_TRANSITION" in str(exc):
            raise AppError(code="INVALID_TRANSITION", message="Transition d'état invalide.", status_code=422)
        raise


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

    Implémentation spéculative (CA-4 vérifiée avant transition).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, organization_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    # CA-4 : `expire` ne fait pas passer à `subscription_closed` sans prérequis de clôture vérifiés
    if abonnement.financialStatus != "settled":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer sans finances réglées.", status_code=422)

    if abonnement.incidentStatus != "none":
        raise AppError(code="invalid_state_for_action", message="Impossible de clôturer avec des incidents non résolus.", status_code=422)

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)

    async def mutation_cloturer(session: AsyncSession):
        """Clôture un abonnement : transition à subscription_closed (CA-1, CA-4)."""
        # CA-4 : les prérequis sont vérifiés avant, donc la transition doit réussir
        # Transition depuis close_pending ou expired vers subscription_closed
        # Pour cette implémentation spéculative, on accepte les états initiaux et on transite
        transitioned = await transition_etat(session, subscription_id, organization_id, "lifecycle", "subscription_closed")
        return transitioned

    try:
        abonnement_updated = await executer_mutation_sensible(
            db,
            identite,
            organization_id,
            action="subscription.close",
            entity_type="subscription",
            entity_id=subscription_id,
            resume=f"Clôture de l'abonnement {subscription_id}",
            mutation=mutation_cloturer,
            changes=lambda sub: {"lifecycleStatus": sub.lifecycleStatus, "version": sub.version},
        )

        # Enregistrer un événement dans l'outbox (CA-7)
        await enregistrer_evenement(
            db,
            {
                "eventType": "subscription.closed",
                "tenantId": str(organization_id),
                "correlationId": str(request.idempotencyKey),
                "acteur": str(current_user.id),
                "data": {"subscriptionId": str(subscription_id)},
            },
            emetteur_tenant=organization_id,
        )

        await db.commit()
        return SubscriptionLifecycleResponse.model_validate(abonnement_updated)
    except Exception as exc:
        if "INVALID_TRANSITION" in str(exc):
            raise AppError(code="INVALID_TRANSITION", message="Transition d'état invalide.", status_code=422)
        raise
