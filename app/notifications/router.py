"""Routes du module Notifications (capacité partagée, core) — montées à la
racine `/notifications` (jamais sous `/zylo-liquid` : ce module sert tous
les modules métier, pas seulement Zylo Liquid)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.identity.models import User
from app.notifications import service
from app.notifications.schemas import CreatePushSubscriptionRequest, PushSubscriptionResponse, VapidPublicKeyResponse
from app.rbac.service import get_current_organization_id

router = APIRouter()


@router.get(
    "/vapid-public-key",
    response_model=VapidPublicKeyResponse,
    summary="Clé publique VAPID",
    description="Clé publique VAPID à utiliser par le navigateur pour s'abonner au Web Push (`PushManager.subscribe`).",
)
async def get_vapid_public_key() -> VapidPublicKeyResponse:
    return VapidPublicKeyResponse(publicKey=settings.VAPID_PUBLIC_KEY)


@router.post(
    "/push-subscriptions",
    response_model=PushSubscriptionResponse,
    summary="Enregistrer un abonnement Web Push",
    description="Enregistre (ou met à jour si le même `endpoint` existe déjà) l'abonnement Web Push du navigateur courant pour l'utilisateur connecté.",
)
async def create_push_subscription(
    data: CreatePushSubscriptionRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    return await service.create_push_subscription(db, organization_id, current_user.id, data)


@router.delete(
    "/push-subscriptions/{subscription_id}",
    status_code=204,
    summary="Supprimer un abonnement Web Push",
    description="Désinscrit ce navigateur des notifications push — n'a aucun effet si l'abonnement n'appartient pas à l'utilisateur connecté.",
)
async def delete_push_subscription(
    subscription_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_push_subscription(db, organization_id, current_user.id, subscription_id)
