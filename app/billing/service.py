import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.idempotency import empreinte_portee, idempotent_command, portee_idempotence
from app.billing.models import Invoice, PaymentAttempt, Plan, PlanVersion, Subscription, SubscriptionEntitlement
from app.core.errors import AppError


async def get_or_create_plan(
    db: AsyncSession, module_code: str, code: str, name: str, price_cents: int, currency: str, period_days: int
) -> Plan:
    """Catalogue : un plan existant est renvoyé tel quel. Un plan de même code
    avec un prix ou une devise différents est refusé (409) : un prix ne se
    réécrit jamais en silence (T-019)."""
    result = await db.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    if plan:
        if plan.priceCents != price_cents or plan.currency != currency:
            raise AppError(code="plan_conflict", message=f"Le plan {code} existe déjà avec un autre prix ou une autre devise.", status_code=409)
        await ensure_initial_plan_version(db, plan)
        return plan
    plan = Plan(moduleCode=module_code, code=code, name=name, priceCents=price_cents, currency=currency, periodDays=period_days)
    db.add(plan)
    await db.flush()
    db.add(PlanVersion(
        planId=plan.id, version=1, amountMinor=price_cents, currency=currency,
        periodDays=period_days, entitlementCodes=[], status="active", effectiveAt=datetime.now(timezone.utc),
    ))
    await db.commit()
    await db.refresh(plan)
    return plan


async def ensure_initial_plan_version(db: AsyncSession, plan: Plan) -> PlanVersion:
    version = await db.scalar(select(PlanVersion).where(PlanVersion.planId == plan.id).order_by(PlanVersion.version.desc()))
    if version is not None:
        return version
    version = PlanVersion(
        planId=plan.id, version=1, amountMinor=int(plan.priceCents), currency=plan.currency,
        periodDays=plan.periodDays, entitlementCodes=[], status="active", effectiveAt=datetime.now(timezone.utc),
    )
    db.add(version)
    await db.flush()
    return version


async def publish_plan_version(
    db: AsyncSession, plan_code: str, amount_minor: int, currency: str,
    period_days: int, entitlement_codes: list[str],
) -> PlanVersion:
    """Publish an immutable price/entitlement snapshot; prior subscriptions
    continue pointing at their original version."""
    plan = await db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        raise AppError(code="plan_not_found", message=f"Plan inconnu : {plan_code}.", status_code=404)
    if amount_minor < 0 or not 1 <= period_days <= 3650:
        raise AppError(code="plan_version_invalid", message="Prix ou période invalide.", status_code=422)
    current = await db.scalar(select(PlanVersion).where(
        PlanVersion.planId == plan.id, PlanVersion.status == "active"
    ).order_by(PlanVersion.version.desc()))
    if current and current.amountMinor == amount_minor and current.currency == currency and current.periodDays == period_days and current.entitlementCodes == entitlement_codes:
        return current
    now = datetime.now(timezone.utc)
    if current:
        current.status = "archived"
    next_version = (await db.scalar(select(PlanVersion.version).where(
        PlanVersion.planId == plan.id
    ).order_by(PlanVersion.version.desc()).limit(1)) or 0) + 1
    version = PlanVersion(
        planId=plan.id, version=next_version, amountMinor=amount_minor, currency=currency,
        periodDays=period_days, entitlementCodes=sorted(set(entitlement_codes)),
        status="active", effectiveAt=now,
    )
    db.add(version)
    # Legacy columns remain a compatibility read model; subscriptions and
    # invoices always snapshot the immutable version instead.
    plan.priceCents = amount_minor
    plan.currency = currency
    plan.periodDays = period_days
    await db.commit()
    await db.refresh(version)
    return version


async def create_trial_subscription(
    db: AsyncSession, organization_id: uuid.UUID, plan_code: str,
    actor_user_id: uuid.UUID, request_id: str | None = None,
) -> Subscription:
    """Point d'insertion futur d'un PaymentProvider réel : pour l'instant tout
    abonnement démarre en 'trial', jamais 'active' (aucun paiement réel n'a
    lieu dans ce socle — grande_phases.md §10)."""
    result = await db.execute(select(Plan).where(Plan.code == plan_code))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise AppError(code="plan_not_found", message=f"Plan inconnu : {plan_code}.", status_code=404)
    version = await ensure_initial_plan_version(db, plan)

    existing = await db.execute(
        select(Subscription).where(
            Subscription.organizationId == organization_id,
            Subscription.planId == plan.id,
            Subscription.status.in_(["trial", "active"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="subscription_already_active", message="Un abonnement actif existe déjà pour ce plan.", status_code=409)

    now = datetime.now(timezone.utc)
    subscription = Subscription(
        organizationId=organization_id,
        planId=plan.id,
        planVersionId=version.id,
        status="trial",
        startDate=now,
        endDate=now + timedelta(days=version.periodDays),
    )
    db.add(subscription)
    await db.flush()
    for entitlement_code in version.entitlementCodes:
        db.add(SubscriptionEntitlement(
            organizationId=organization_id, subscriptionId=subscription.id,
            moduleCode=plan.moduleCode, entitlementCode=entitlement_code,
            status="active", startsAt=now, endsAt=subscription.endDate,
        ))
    await record_audit_event(
        db, organization_id, actor_user_id, action="billing.subscription.trial.create",
        entity_type="Subscription", entity_id=subscription.id,
        summary=(f"Création d'un abonnement d'essai au plan {plan.code}" + (f" (request_id={request_id})" if request_id else "")),
        changes={"status": {"before": None, "after": "trial"}, "planVersion": version.version},
    )
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def current_subscription(db: AsyncSession, organization_id: uuid.UUID) -> tuple[Subscription, list[str]] | None:
    subscription = await db.scalar(
        select(Subscription).where(
            Subscription.organizationId == organization_id,
            Subscription.status.in_(["trial", "active"]),
        ).order_by(Subscription.endDate.desc())
    )
    if subscription is None:
        return None
    entitlements = list((await db.scalars(select(SubscriptionEntitlement.entitlementCode).where(
        SubscriptionEntitlement.subscriptionId == subscription.id,
        SubscriptionEntitlement.status == "active",
    ))).all())
    return subscription, entitlements


ROUTE_CREATION_FACTURE = "billing.invoice.create"


@idempotent_command(route=ROUTE_CREATION_FACTURE, result_model=Invoice)
async def create_invoice(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID,
    subscription_id: uuid.UUID, idempotency_key: str, request_id: str | None = None,
) -> Invoice:
    """Émet une facture pour un abonnement, sous contrôle d'idempotence (BE-072).

    Le décorateur `idempotent_command` traite la portée (principal, route, clé) et
    l'empreinte de commande avant ce corps : une clé déjà utilisée par le même
    principal pour la même commande renvoie la facture initiale ; pour une autre
    commande, `DUPLICATE` ; une clé d'un autre principal ne rejoue jamais le
    résultat d'autrui. Ce corps ne voit donc que les demandes nouvelles.

    `invoice.idempotencyKey` reçoit l'empreinte de la portée (et non la clé brute) :
    la contrainte unique de la colonne reste active jusqu'à migration, sans
    bloquer un second principal. Un abonnement absent ou hors organisation renvoie
    `subscription_not_found` ; la réservation de la clé est alors retirée par le décorateur.
    """
    subscription = await db.scalar(select(Subscription).where(
        Subscription.id == subscription_id, Subscription.organizationId == organization_id
    ))
    if subscription is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    plan = await db.get(Plan, subscription.planId)
    version = await db.get(PlanVersion, subscription.planVersionId) if subscription.planVersionId else await ensure_initial_plan_version(db, plan)
    now = datetime.now(timezone.utc)
    invoice = Invoice(
        subscriptionId=subscription.id, amountCents=version.amountMinor,
        amountMinor=version.amountMinor, currency=version.currency,
        status="pending", issuedAt=now,
        idempotencyKey=empreinte_portee(portee_idempotence(actor_user_id, ROUTE_CREATION_FACTURE, idempotency_key)),
    )
    db.add(invoice)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise billing_error(BillingErrorCode.DUPLICATE) from exc
    await record_audit_event(
        db, organization_id, actor_user_id, action="billing.invoice.create",
        entity_type="Invoice", entity_id=invoice.id,
        summary=(f"Création d'une facture pour l'abonnement {subscription.id}" + (f" (request_id={request_id})" if request_id else "")),
        changes={"amountMinor": {"before": None, "after": version.amountMinor}, "currency": {"before": None, "after": version.currency}},
    )
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def list_organization_invoices(db: AsyncSession, organization_id: uuid.UUID) -> list[Invoice]:
    return list((await db.scalars(
        select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(Subscription.organizationId == organization_id).order_by(Invoice.issuedAt.desc())
    )).all())


async def list_invoice_payment_attempts(
    db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID,
) -> list[PaymentAttempt]:
    owns_invoice = await db.scalar(
        select(Invoice.id).join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(Invoice.id == invoice_id, Subscription.organizationId == organization_id)
    )
    if owns_invoice is None:
        raise AppError(code="invoice_not_found", message="Facture introuvable.", status_code=404)
    return list((await db.scalars(select(PaymentAttempt).where(
        PaymentAttempt.invoiceId == invoice_id
    ).order_by(PaymentAttempt.requestedAt.desc()))).all())


async def start_payment_attempt(
    db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID,
    idempotency_key: str,
) -> PaymentAttempt:
    """Flutterwave checkout is intentionally unavailable until a tested,
    server-side sandbox client and transaction verification are configured.
    This path never creates a misleading attempt or contacts a provider."""
    invoice = await db.scalar(
        select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId)
        .where(Invoice.id == invoice_id, Subscription.organizationId == organization_id)
    )
    if invoice is None:
        raise AppError(code="invoice_not_found", message="Facture introuvable.", status_code=404)
    raise AppError(
        code="PROVIDER_UNAVAILABLE",
        message="Le paiement Flutterwave sandbox n'est pas configuré. Aucun paiement n'a été initié.",
        status_code=503,
    )
