import uuid

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.billing import service as billing_service
from app.billing.models import PaymentWebhookEvent, Plan
from app.core.database import get_db
from app.core.errors import AppError
from app.identity.models import Organization
from app.identity.models import User
from app.modules_registry import service as modules_service
from app.operator.audit import record_operator_read
from app.operator.permissions import require_operator
from app.operator.schemas import (
    OperatorHealthResponse,
    OperatorModuleItem,
    OperatorOrganizationItem,
    OperatorOrganizationOverview,
    OperatorPaymentEvent,
    OperatorRequestTrace,
    OperatorSubscriptionItem,
    OperatorTraceEvent,
)
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/organizations", response_model=Page[OperatorOrganizationItem])
async def list_organizations(
    request: Request,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> Page[OperatorOrganizationItem]:
    stmt = select(Organization).where(Organization.deletedAt.is_(None)).order_by(Organization.name, Organization.id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await db.scalars(stmt.limit(pagination.limit).offset(pagination.offset))).all())
    await record_operator_read(
        db, actor_user_id=current_user.id, scope="platform", action="organization.list",
        target_type="organization_list", outcome="success", request_id=request.state.request_id,
    )
    return Page(
        data=[OperatorOrganizationItem.model_validate(row) for row in rows],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.get("/organizations/{organization_id}", response_model=OperatorOrganizationOverview)
async def organization_overview(
    organization_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> OperatorOrganizationOverview:
    org = await db.get(Organization, organization_id)
    if org is None or org.deletedAt is not None:
        await record_operator_read(
            db, actor_user_id=current_user.id, scope="organization", action="organization.read",
            target_type="organization", target_id=organization_id, outcome="not_found",
            request_id=request.state.request_id,
        )
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    current = await billing_service.current_subscription(db, organization_id)
    subscription_out = None
    if current is not None:
        subscription, _ = current
        plan = await db.get(Plan, subscription.planId)
        subscription_out = OperatorSubscriptionItem(
            id=subscription.id, status=subscription.status, planCode=plan.code, planName=plan.name,
            startDate=subscription.startDate, endDate=subscription.endDate,
        )
    installed = await modules_service.list_installed_modules(db, organization_id)
    await record_operator_read(
        db, actor_user_id=current_user.id, scope="organization", action="organization.read",
        target_type="organization", target_id=organization_id, outcome="success",
        request_id=request.state.request_id,
    )
    return OperatorOrganizationOverview(
        organization=OperatorOrganizationItem.model_validate(org),
        subscription=subscription_out,
        modules=[OperatorModuleItem(moduleCode=m.moduleCode, name=m.name, status=m.status) for m in installed],
    )


@router.get("/health", response_model=OperatorHealthResponse)
async def operator_health(request: Request, db: AsyncSession = Depends(get_db)) -> OperatorHealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        await db.rollback()
        db_status = "unavailable"
    return OperatorHealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        requestId=getattr(request.state, "request_id", None),
    )


@router.get("/requests/{request_id}", response_model=OperatorRequestTrace)
async def lookup_request(
    request: Request,
    request_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> OperatorRequestTrace:
    # Audit summaries include request_id only for a small subset of mutations;
    # webhook events retain a structured requestId. No raw summary, user data,
    # request body, or authentication data is returned.
    audits = list((await db.scalars(select(AuditLog).where(
        AuditLog.summary.contains(f"(request_id={request_id})")
    ).order_by(AuditLog.createdAt.desc()).limit(100))).all())
    webhooks = list((await db.scalars(select(PaymentWebhookEvent).where(
        PaymentWebhookEvent.requestId == request_id
    ).order_by(PaymentWebhookEvent.createdAt.desc()).limit(100))).all())
    events = [OperatorTraceEvent(source="audit", action=a.action, entityType=a.entityType, createdAt=a.createdAt) for a in audits]
    events.extend(
        OperatorTraceEvent(source="payment_webhook", action=w.eventType, entityType="PaymentWebhookEvent", createdAt=w.createdAt)
        for w in webhooks
    )
    await record_operator_read(
        db, actor_user_id=current_user.id, scope="platform", action="request_trace.read",
        target_type="request_trace", outcome="found" if events else "not_found",
        request_id=request.state.request_id,
    )
    return OperatorRequestTrace(requestId=request_id, found=bool(events), events=events)


@router.get("/payment-events/{event_id}", response_model=OperatorPaymentEvent)
async def lookup_payment_event(
    request: Request,
    event_id: str = Path(min_length=1, max_length=160),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> PaymentWebhookEvent:
    event = await db.scalar(select(PaymentWebhookEvent).where(
        PaymentWebhookEvent.provider == "flutterwave", PaymentWebhookEvent.eventId == event_id
    ))
    if event is None:
        await record_operator_read(
            db, actor_user_id=current_user.id, scope="platform", action="payment_event.read",
            target_type="payment_event", outcome="not_found", request_id=request.state.request_id,
        )
        raise AppError(code="payment_event_not_found", message="Événement de paiement introuvable.", status_code=404)
    await record_operator_read(
        db, actor_user_id=current_user.id, scope="platform", action="payment_event.read",
        target_type="payment_event", outcome="success", request_id=request.state.request_id,
    )
    return event
