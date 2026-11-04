"""Routes du module Notifications (capacité partagée, core) — montées à la
racine `/notifications` (jamais sous `/zylo-liquid` : ce module sert tous
les modules métier, pas seulement Zylo Liquid)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.identity.models import User
from app.notifications import service
from app.notifications.schemas import (
    CreatePushSubscriptionRequest,
    NotificationInboxItemResponse,
    PushSubscriptionResponse,
    VapidPublicKeyResponse,
)
from app.rbac.service import get_current_organization_id
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page

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
    description=(
        "Désinscrit ce navigateur des notifications push côté serveur. Réponses : 204 si l'abonnement "
        "appartenait à l'utilisateur connecté et a été supprimé ; 401 sans session ; 404 si l'abonnement "
        "est absent ou appartient à un autre utilisateur (sans fuite d'existence)."
    ),
)
async def delete_push_subscription(
    subscription_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_push_subscription(db, organization_id, current_user.id, subscription_id)


@router.get("/inbox", response_model=Page[NotificationInboxItemResponse], summary="Notifications de l'utilisateur courant")
async def list_inbox(
    pagination: PaginationParams = Depends(),
    unreadOnly: bool = Query(False),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Liste paginée, limitée au compte courant et à l'organisation active."""
    return await service.list_inbox_items(
        db,
        organization_id=organization_id,
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        unread_only=unreadOnly,
    )


@router.get("/inbox/{item_id}", response_model=NotificationInboxItemResponse, summary="Détail d'une notification propre au compte")
async def get_inbox_item(
    item_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationInboxItemResponse:
    item = await service.get_inbox_item(db, organization_id=organization_id, user_id=current_user.id, item_id=item_id)
    return NotificationInboxItemResponse.model_validate(item)


@router.patch(
    "/inbox/{item_id}",
    response_model=NotificationInboxItemResponse,
    summary="Marquer sa notification comme lue",
    description="Pose `readAt` si besoin ; répéter l'appel est idempotent. 404 si l'élément n'appartient pas au compte courant.",
)
@router.patch(
    "/inbox/{item_id}/read",
    response_model=NotificationInboxItemResponse,
    include_in_schema=False,
)
async def mark_inbox_item_read(
    item_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationInboxItemResponse:
    """Route définitive `PATCH /inbox/{itemId}` (BE-035). L'alias `/inbox/{itemId}/read`
    reste servi, masqué du schéma OpenAPI, pour le contrat déjà documenté dans
    `docs/architecture/notifications/inbox-api.md` ; il sera retiré quand ce document
    sera aligné."""
    item = await service.mark_inbox_item_read(db, organization_id=organization_id, user_id=current_user.id, item_id=item_id)
    return NotificationInboxItemResponse.model_validate(item)
