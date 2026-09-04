import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Plan, Subscription
from app.core.errors import AppError


async def get_or_create_plan(
    db: AsyncSession, module_code: str, code: str, name: str, price_cents: int, currency: str, period_days: int
) -> Plan:
    result = await db.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    if plan:
        return plan
    plan = Plan(moduleCode=module_code, code=code, name=name, priceCents=price_cents, currency=currency, periodDays=period_days)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def create_trial_subscription(db: AsyncSession, organization_id: uuid.UUID, plan_code: str) -> Subscription:
    """Point d'insertion futur d'un PaymentProvider réel : pour l'instant tout
    abonnement démarre en 'trial', jamais 'active' (aucun paiement réel n'a
    lieu dans ce socle — grande_phases.md §10)."""
    result = await db.execute(select(Plan).where(Plan.code == plan_code))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise AppError(code="plan_not_found", message=f"Plan inconnu : {plan_code}.", status_code=404)

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
        status="trial",
        startDate=now,
        endDate=now + timedelta(days=plan.periodDays),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription
