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


class NotificationResponse(BaseModel):
    """Notification d'un destinataire (BE-171). `motifSuppression` n'est renseigné que
    pour `statut = supprimee`. Aucune adresse de destinataire n'y figure."""

    id: uuid.UUID
    eventId: uuid.UUID
    categorieCode: str
    statut: str
    motifSuppression: str | None
    creeAt: datetime

    model_config = {"from_attributes": True}


class LivraisonResponse(BaseModel):
    """Une tentative de remise à un canal (BE-171, CA-2). Ne porte aucun champ de
    destinataire : seuls le canal (nom opaque), le résultat et les dates de tentative."""

    id: uuid.UUID
    canal: str
    tentativeNo: int
    resultat: str
    codeErreur: str | None
    prochaineTentativeAt: datetime | None
    creeAt: datetime

    model_config = {"from_attributes": True}


class PreferenceCategorieRequest(BaseModel):
    """Corps de `PUT /api/v1/notification-preferences` (BE-212) : une catégorie et le choix
    de l'utilisateur courant. `enabled: false` vaut désinscription de la catégorie."""

    category: str = Field(min_length=1, max_length=80)
    enabled: bool


class PreferenceCategorieResponse(BaseModel):
    """Préférence de l'utilisateur courant pour une catégorie (BE-212). Aucun secret ni
    donnée d'un autre utilisateur n'y figure."""

    category: str
    enabled: bool
    updatedAt: datetime
