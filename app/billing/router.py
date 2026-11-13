import uuid
import hmac
import os

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import entitlements as calcul_entitlements
from app.billing import service
from app.billing.models import Invoice, Plan, PlanVersion, Subscription
from app.billing.payment_provider import FlutterwaveTestProvider
from app.billing.webhooks import traiter_evenement_webhook
from app.billing.permissions import SUBSCRIPTION_MANAGE, SUBSCRIPTION_READ
from app.billing.schemas import (
    CreateInvoiceRequest, CreateSubscriptionRequest, EntitlementResponse, InvoiceResponse,
    PaymentAttemptResponse, PaymentWebhookAck, PlanResponse, SubscriptionResponse,
    PaymentProviderStatus,
)
from app.core.errors import AppError
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter()
_test_provider = FlutterwaveTestProvider()


# T-019 / T-050 (option A, recommandation vérifiée) : pas de création de plan par API.
# Le catalogue de plans est seedé par une commande explicite (service.get_or_create_plan) ;
# une création par un utilisateur authentifié n'est plus possible (POST /plans n'existe plus).


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[Plan]:
    plans = list((await db.scalars(select(Plan).order_by(Plan.code))).all())
    response = []
    for plan in plans:
        version = await db.scalar(select(PlanVersion).where(
            PlanVersion.planId == plan.id, PlanVersion.status == "active"
        ).order_by(PlanVersion.version.desc()))
        response.append(PlanResponse(
            id=plan.id, moduleCode=plan.moduleCode, code=plan.code, name=plan.name,
            priceCents=int(plan.priceCents), currency=plan.currency, periodDays=plan.periodDays,
            version=version.version if version else 1,
            amountMinor=version.amountMinor if version else int(plan.priceCents),
            entitlementCodes=version.entitlementCodes if version else [],
        ))
    return response


@router.get("/payment-provider", response_model=PaymentProviderStatus)
async def payment_provider_status() -> PaymentProviderStatus:
    return PaymentProviderStatus(
        provider="flutterwave", mode="test", configured=False, checkoutAvailable=False,
        message="Checkout sandbox non configuré; aucune transaction n'est disponible.",
    )


@router.post(
    "/organizations/{organization_id}/subscriptions",
    response_model=SubscriptionResponse,
    status_code=201,
    dependencies=[Depends(require_permission(SUBSCRIPTION_MANAGE))],
)
async def create_subscription(
    organization_id: uuid.UUID,
    data: CreateSubscriptionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    return await service.create_trial_subscription(
        db, organization_id, data.planCode, current_user.id, getattr(request.state, "request_id", None)
    )


@router.get(
    "/organizations/{organization_id}/subscription",
    response_model=SubscriptionResponse | None,
    dependencies=[Depends(require_organization_member)],
)
async def get_current_subscription(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    current = await service.current_subscription(db, organization_id)
    if current is None:
        return None
    subscription, entitlement_codes = current
    return SubscriptionResponse(
        id=subscription.id, organizationId=subscription.organizationId, planId=subscription.planId,
        planVersionId=subscription.planVersionId, status=subscription.status,
        startDate=subscription.startDate, endDate=subscription.endDate,
        entitlementCodes=entitlement_codes,
    )


@router.get(
    "/organizations/{organization_id}/invoices",
    response_model=Page[InvoiceResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_invoices(
    organization_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId).where(
        Subscription.organizationId == organization_id
    ).order_by(Invoice.issuedAt.desc())
    return await paginate(db, stmt, pagination, InvoiceResponse)


@router.post(
    "/organizations/{organization_id}/invoices",
    response_model=InvoiceResponse,
    status_code=201,
    dependencies=[Depends(require_permission(SUBSCRIPTION_MANAGE))],
)
async def create_invoice(
    organization_id: uuid.UUID,
    data: CreateInvoiceRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=120),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_invoice(
        db, organization_id, current_user.id,
        data.subscriptionId, idempotency_key, getattr(request.state, "request_id", None),
    )


@router.get(
    "/organizations/{organization_id}/invoices/{invoice_id}/payment-attempts",
    response_model=list[PaymentAttemptResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_payment_attempts(
    organization_id: uuid.UUID, invoice_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    return await service.list_invoice_payment_attempts(db, organization_id, invoice_id)


@router.post(
    "/organizations/{organization_id}/invoices/{invoice_id}/payment-attempts",
    response_model=PaymentAttemptResponse,
    status_code=201,
    dependencies=[Depends(require_permission(SUBSCRIPTION_MANAGE))],
)
async def start_payment_attempt(
    organization_id: uuid.UUID,
    invoice_id: uuid.UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=120),
    db: AsyncSession = Depends(get_db),
):
    return await service.start_payment_attempt(db, organization_id, invoice_id, idempotency_key)


@router.post("/provider-events", response_model=PaymentWebhookAck, summary="Ingestion d'un évènement fournisseur de paiement")
@router.post("/webhooks/flutterwave", response_model=PaymentWebhookAck, include_in_schema=False)
async def flutterwave_webhook(
    request: Request,
    verif_hash: str | None = Header(default=None, alias="verif-hash"),
    db: AsyncSession = Depends(get_db),
):
    """Entrée des évènements fournisseur de paiement : vérifie la signature, puis délègue à BE-029.

    Route canonique : `POST /api/v1/billing/provider-events` (BE-083). L'ancienne
    adresse `/webhooks/flutterwave` reste servie, sans être documentée, pour les
    appels existants ; les deux chemins sont le même handler, sans second code.

    Contrat de signature (ACTF-11) : l'en-tête `verif-hash` doit égaler le secret
    `FLUTTERWAVE_WEBHOOK_SECRET`. Secret non configuré : 503 `PROVIDER_UNAVAILABLE`.
    Signature absente ou fausse : 401 `webhook_signature_invalid`, sans lecture du corps
    ni écriture. Signature valide : le corps brut est transmis tel quel à
    `traiter_evenement_webhook` (BE-029), avec `signature_verifiee=True`. La route
    n'applique aucune règle métier. Ce endpoint ne règle jamais une facture ni
    n'accorde d'entitlement.
    """
    secret = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET", "")
    if not secret:
        raise AppError(code="PROVIDER_UNAVAILABLE", message="Le webhook Flutterwave n'est pas configuré.", status_code=503)
    if not verif_hash or not hmac.compare_digest(verif_hash, secret):
        raise AppError(code="webhook_signature_invalid", message="Signature de webhook invalide.", status_code=401)
    raw = await request.body()
    resultat = await traiter_evenement_webhook(
        db, corps=raw, signature_verifiee=True,
        request_id=getattr(request.state, "request_id", None),
    )
    return PaymentWebhookAck(received=True, duplicate=resultat.duplicate)


# BE-026 : lecture de l'abonnement et des entitlements de l'organisation COURANTE.
# Montée sous `/api/v1/organizations` (voir app/api/v1/router.py) : l'organisation
# n'est jamais dans le chemin, elle vient de l'en-tête `X-Organization-Id`, validé
# par `get_current_organization_id` (membership actif, sinon 404 uniforme). La
# permission `billing.subscription.read` est ensuite exigée (403 sinon).
current_organization_router = APIRouter()


@current_organization_router.get(
    "/current/subscription",
    response_model=SubscriptionResponse | None,
    summary="Lire l'abonnement de l'organisation courante",
    dependencies=[Depends(require_permission(SUBSCRIPTION_READ))],
)
async def read_current_subscription(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie l'abonnement actif ou d'essai de l'organisation courante, ou `null`.

    `null` (et non une erreur) est l'état vide d'une organisation sans abonnement :
    aucun plan, aucune facture ni abonnement n'est créé ni suggéré à la lecture.
    Les codes d'entitlement listés sont ceux qui sont actifs pour cet abonnement.
    Aucune donnée fournisseur de paiement n'est exposée.
    """
    current = await service.current_subscription(db, organization_id)
    if current is None:
        return None
    subscription, entitlement_codes = current
    return SubscriptionResponse(
        id=subscription.id, organizationId=subscription.organizationId, planId=subscription.planId,
        planVersionId=subscription.planVersionId, status=subscription.status,
        startDate=subscription.startDate, endDate=subscription.endDate,
        entitlementCodes=entitlement_codes,
    )


@current_organization_router.get(
    "/current/entitlements",
    response_model=list[EntitlementResponse],
    summary="Lire les entitlements de l'organisation courante",
    dependencies=[Depends(require_permission(SUBSCRIPTION_READ))],
)
async def read_current_entitlements(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie les entitlements de l'organisation courante avec leur état calculé.

    Seules les lignes de l'organisation courante sont lues : un entitlement d'une
    autre organisation n'apparaît jamais (isolation). L'état (`etat`) est calculé à
    la lecture par `app/billing/entitlements.py::calculer_entitlements` (`expired`
    dès que la date de fin est dépassée pour une ligne active). Liste vide si
    l'organisation n'a aucun entitlement.
    """
    return await calcul_entitlements.calculer_entitlements(db, organization_id)

