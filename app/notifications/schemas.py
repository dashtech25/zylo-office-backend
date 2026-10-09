"""Schémas Pydantic du module Notifications."""

import uuid

from pydantic import BaseModel, Field


class VapidPublicKeyResponse(BaseModel):
    publicKey: str = Field(description="Clé publique VAPID (base64url) — à passer telle quelle à `PushManager.subscribe({ applicationServerKey })` côté navigateur.")


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class CreatePushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    userAgent: str | None = None


class PushSubscriptionResponse(BaseModel):
    id: uuid.UUID
    endpoint: str

    model_config = {"from_attributes": True}
