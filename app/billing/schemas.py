import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    version: int = 1
    amountMinor: int | None = None
    entitlementCodes: list[str] = Field(default_factory=list)

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
    planVersionId: uuid.UUID | None = None
    entitlementCodes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CreateInvoiceRequest(BaseModel):
    subscriptionId: uuid.UUID


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    subscriptionId: uuid.UUID
    amountMinor: int | None = None
    currency: str
    status: str
    issuedAt: datetime
    paidAt: datetime | None = None

    model_config = {"from_attributes": True}


class PaymentAttemptResponse(BaseModel):
    id: uuid.UUID
    invoiceId: uuid.UUID
    provider: str
    mode: str
    amountMinor: int
    currency: str
    status: str
    checkoutUrl: str | None = None
    requestedAt: datetime

    model_config = {"from_attributes": True}


class PaymentWebhookAck(BaseModel):
    received: bool = True
    duplicate: bool = False


class PaymentProviderStatus(BaseModel):
    provider: str
    mode: str
    configured: bool
    checkoutAvailable: bool
    message: str
