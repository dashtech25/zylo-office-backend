import uuid
from datetime import datetime

from pydantic import BaseModel


class OperatorOrganizationItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}


class OperatorSubscriptionItem(BaseModel):
    id: uuid.UUID
    status: str
    planCode: str
    planName: str
    startDate: datetime
    endDate: datetime


class OperatorModuleItem(BaseModel):
    moduleCode: str
    name: str
    status: str


class OperatorOrganizationOverview(BaseModel):
    organization: OperatorOrganizationItem
    subscription: OperatorSubscriptionItem | None
    modules: list[OperatorModuleItem]


class OperatorHealthResponse(BaseModel):
    status: str
    database: str
    requestId: str | None


class OperatorTraceEvent(BaseModel):
    source: str
    action: str
    entityType: str
    createdAt: datetime


class OperatorRequestTrace(BaseModel):
    requestId: str
    found: bool
    events: list[OperatorTraceEvent]


class OperatorPaymentEvent(BaseModel):
    provider: str
    eventId: str
    eventType: str
    requestId: str | None
    processedAt: datetime | None
    outcome: str
    createdAt: datetime

    model_config = {"from_attributes": True}
