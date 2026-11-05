"""Console opérateur en lecture seule (BE-031), montée sous `/api/v1/admin`.

Routes :
- `GET /api/v1/admin/organizations` : liste des organisations (portée plateforme) ;
- `GET /api/v1/admin/organizations/{organization_id}` : abonnement et modules ;
- `GET /api/v1/admin/requests/{request_id}` : recherche par request ID ;
- `GET /api/v1/admin/sensitive-action-classes` : registre des classes d'action
  sensible et leur fiche standard (BE-127), en lecture seule.

Garde : toutes les routes dépendent de `require_operator` (allowlist serveur
`OPERATOR_READ_USER_IDS`, fail-closed). Hors liste : 403, tentative journalisée.

Chaque consultation (succès, absence, refus, erreur) produit une entrée
`audit_event` d'action `operator.` via `record_operator_read`.

Pas d'écriture : PUT, POST et DELETE reçoivent 405 (aucune route ne les déclare).
Aucun contenu tenant : seuls organisation, abonnement, modules et métadonnées
d'événements techniques sortent de ce module.
"""

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
from app.operator.sensitive_classes import CLASSES
from app.operator.schemas import (
    OperatorHealthResponse,
    OperatorModuleItem,
    OperatorOrganizationItem,
    OperatorOrganizationOverview,
    OperatorPaymentEvent,
    OperatorRequestTrace,
    OperatorSubscriptionItem,
    OperatorTraceEvent,
    SensitiveActionClassItem,
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
    """Liste paginée des organisations non supprimées, en lecture seule.

    Retourne `id`, `name`, `slug` et `status` uniquement. Une lecture réussie est
    journalisée (portée plateforme, action `operator.organization.list`).
    """
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
    """État d'abonnement et modules d'une organisation, sans contenu tenant.

    404 `organization_not_found` si l'organisation est absente ou supprimée
    (la consultation est tout de même journalisée, issue `not_found`).
    """
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


@router.get("/sensitive-action-classes", response_model=list[SensitiveActionClassItem])
async def list_sensitive_action_classes() -> list[SensitiveActionClassItem]:
    """Registre des classes d'action sensible (BE-127), sans écriture.

    Renvoie les huit classes de la définition avec leur fiche standard. Le registre
    est une constante de code (`app/operator/sensitive_classes.py`) : aucune
    lecture de base, aucune route d'écriture (PUT, POST, PATCH, DELETE : 405).
    Garde : `require_operator` de la route (allowlist d'exploitation, 403 sinon).
    """
    return [
        SensitiveActionClassItem(
            code=c.code, libelle=c.libelle, requiresDoubleValidation=c.requiresDoubleValidation,
            requiresReauth=c.requiresReauth, approvalWindow=c.approvalWindow, reversible=c.reversible,
            risk_note=c.risk_note, fiche=dict(c.fiche),
        )
        for c in CLASSES
    ]


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
    """Recherche les événements liés à un request ID.

    Issues (BE-031 CA-4) :
    - `found` : 200, `outcome = found` ;
    - `not_found` : 200, `outcome = not_found`, `events` vide ;
    - `refused` : 403 par la garde `require_operator` (journalisé avant la réponse) ;
    - `error` : 503 `request_trace_error` si la base échoue pendant la recherche.

    Piège évité : l'erreur est journalisée (`outcome = error`) puis relancée en
    503 propre, au lieu d'une 500 sans trace. Le `rollback` précède l'écriture du
    journal pour que la session soit utilisable.
    """
    # Identifiant lu avant le `rollback` : celui-ci expire les objets ORM, et relire
    # `current_user.id` ensuite déclencherait un chargement paresseux hors contexte async.
    acteur_id = current_user.id
    try:
        events = await _chercher_traces(db, request_id)
    except SQLAlchemyError:
        await db.rollback()
        await record_operator_read(
            db, actor_user_id=acteur_id, scope="platform", action="request_trace.read",
            target_type="request_trace", outcome="error", request_id=request.state.request_id,
        )
        raise AppError(code="request_trace_error", message="Recherche indisponible, réessayez.", status_code=503)
    outcome = "found" if events else "not_found"
    await record_operator_read(
        db, actor_user_id=acteur_id, scope="platform", action="request_trace.read",
        target_type="request_trace", outcome=outcome, request_id=request.state.request_id,
    )
    return OperatorRequestTrace(requestId=request_id, found=bool(events), outcome=outcome, events=events)


async def _chercher_traces(db: AsyncSession, request_id: str) -> list[OperatorTraceEvent]:
    """Lit les événements d'audit et de webhook portant ce request ID (100 au plus par source).

    Les résumés d'audit ne contiennent le request ID que pour un petit sous-ensemble
    de mutations ; les webhooks le portent dans une colonne dédiée. Aucun résumé
    brut, donnée utilisateur, corps de requête ou donnée d'authentification n'est
    renvoyé : seuls source, action, type d'entité et date sortent.
    """
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
    return events


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
