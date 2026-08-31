import uuid
from datetime import datetime

from pydantic import BaseModel


class CreatePlanRequest(BaseModel):
    moduleCode: str
    code: str
    name: str
    priceCents: int
    currency: str = "XAF"
    periodDays: int = 30


class PlanResponse(BaseModel):
    id: uuid.UUID
    moduleCode: str
    code: str
    name: str
    priceCents: int
    currency: str
    periodDays: int

    model_config = {"from_attributes": True}


class CreateSubscriptionRequest(BaseModel):
    planCode: str


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    planId: uuid.UUID
    status: str
    startDate: datetime
    endDate: datetime

    model_config = {"from_attributes": True}
