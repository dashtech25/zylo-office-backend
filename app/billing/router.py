import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service
from app.billing.models import Plan, Subscription
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.schemas import CreatePlanRequest, CreateSubscriptionRequest, PlanResponse, SubscriptionResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.service import require_permission

router = APIRouter()


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(
    data: CreatePlanRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Plan:
    return await service.get_or_create_plan(
        db, data.moduleCode, data.code, data.name, data.priceCents, data.currency, data.periodDays
    )


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[Plan]:
    result = await db.execute(select(Plan))
    return list(result.scalars().all())


@router.post(
    "/organizations/{organization_id}/subscriptions",
    response_model=SubscriptionResponse,
    status_code=201,
    dependencies=[Depends(require_permission(SUBSCRIPTION_MANAGE))],
)
async def create_subscription(
    organization_id: uuid.UUID, data: CreateSubscriptionRequest, db: AsyncSession = Depends(get_db)
) -> Subscription:
    return await service.create_trial_subscription(db, organization_id, data.planCode)
