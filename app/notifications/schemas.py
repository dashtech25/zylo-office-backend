"""Schémas Pydantic du module Notifications."""

import uuid

from datetime import datetime

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


class NotificationInboxItemResponse(BaseModel):
    id: uuid.UUID
    category: str
    title: str
    body: str
    createdAt: datetime
    readAt: datetime | None

    model_config = {"from_attributes": True}


class PreferenceNotificationResponse(BaseModel):
    """Préférence d'un utilisateur pour une catégorie (BE-168). Aucun champ de plage de
    silence ni d'heure calme : elles ne sont pas implémentées (CA-4)."""

    categorieCode: str
    consentement: bool
    horodatageConsentement: datetime
    sourceConsentement: str

    model_config = {"from_attributes": True}


class ModifierPreferenceRequest(BaseModel):
    """Corps de `PUT /notifications/preferences/{categorie_code}`. `consentement: false`
    vaut désinscription de la catégorie."""

    consentement: bool
