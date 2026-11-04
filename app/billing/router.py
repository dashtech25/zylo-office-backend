import uuid
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import entitlements as calcul_entitlements
from app.billing import service
from app.billing.models import Invoice, PaymentWebhookEvent, Plan, PlanVersion, Subscription
from app.billing.payment_provider import FlutterwaveTestProvider
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


@router.post("/webhooks/flutterwave", response_model=PaymentWebhookAck)
async def flutterwave_webhook(
    request: Request,
    verif_hash: str | None = Header(default=None, alias="verif-hash"),
    db: AsyncSession = Depends(get_db),
):
    """Records authenticated events idempotently; it never settles an invoice.

    Settlement awaits a separate server-to-server transaction verification.
    """
    secret = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET", "")
    if not secret:
        raise AppError(code="PROVIDER_UNAVAILABLE", message="Le webhook Flutterwave n'est pas configuré.", status_code=503)
    if not verif_hash or not hmac.compare_digest(verif_hash, secret):
        raise AppError(code="webhook_signature_invalid", message="Signature de webhook invalide.", status_code=401)
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(code="webhook_payload_invalid", message="Payload webhook invalide.", status_code=400) from exc
    event_data = payload.get("data") if isinstance(payload, dict) else None
    event_id = str(payload.get("id") or (event_data or {}).get("id") or "") if isinstance(payload, dict) else ""
    event_type = str(payload.get("event") or payload.get("type") or "unknown") if isinstance(payload, dict) else "unknown"
    if isinstance(payload, dict) and not payload.get("id") and isinstance(event_data, dict):
        # Flutterwave v3 events may expose only the transaction ID; include
        # status so a pending -> successful transition is not mistaken for a
        # duplicate delivery of the earlier event.
        event_id = f"{event_type}:{event_id}:{event_data.get('status', 'unknown')}"
    if not event_id or len(event_id) > 160:
        raise AppError(code="webhook_event_id_missing", message="Identifiant d'événement manquant ou invalide.", status_code=400)
    previous = await db.scalar(select(PaymentWebhookEvent).where(
        PaymentWebhookEvent.provider == "flutterwave", PaymentWebhookEvent.eventId == event_id
    ))
    if previous is not None:
        if previous.payloadDigest != hashlib.sha256(raw).hexdigest():
            raise AppError(
                code="webhook_event_conflict",
                message="Cet identifiant d'événement a déjà été reçu avec un contenu différent.",
                status_code=409,
            )
        return PaymentWebhookAck(received=True, duplicate=True)
    payload_digest = hashlib.sha256(raw).hexdigest()
    db.add(PaymentWebhookEvent(
        provider="flutterwave", eventId=event_id, eventType=event_type,
        payloadDigest=payload_digest, signatureVerified=True,
        requestId=getattr(request.state, "request_id", None),
        processedAt=datetime.now(timezone.utc), outcome="recorded_unverified",
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == "flutterwave", PaymentWebhookEvent.eventId == event_id
        ))
        if existing is None:
            raise
        if existing.payloadDigest != payload_digest:
            raise AppError(
                code="webhook_event_conflict",
                message="Cet identifiant d'événement a déjà été reçu avec un contenu différent.",
                status_code=409,
            )
        return PaymentWebhookAck(received=True, duplicate=True)
    return PaymentWebhookAck(received=True, duplicate=False)


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

