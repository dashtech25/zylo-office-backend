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
from typing import Literal

from app.notifications import consultation
from app.notifications import preferences as preferences_service
from app.notifications import service
from app.notifications.schemas import (
    LivraisonResponse,
    ModifierPreferenceRequest,
    NotificationResponse,
    PreferenceNotificationResponse,
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


@router.get(
    "",
    response_model=Page[NotificationResponse],
    summary="Notifications de l'utilisateur courant",
    description=(
        "Notifications dont le compte courant est le destinataire, dans l'organisation active, "
        "plus récentes d'abord. Filtre optionnel `statut` (`en_attente`, `supprimee`, `envoyee`, "
        "`echec`). Détail : `app/notifications/routes.md`."
    ),
)
async def list_notifications(
    statut: Literal["en_attente", "supprimee", "envoyee", "echec"] | None = Query(None),
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Liste paginée (BE-171, CA-1). Le tenant est filtré dans `consultation.py` (CA-5)."""
    return await consultation.lister_notifications(
        db,
        organization_id=organization_id,
        user_id=current_user.id,
        statut=statut,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{notification_id}/livraisons",
    response_model=list[LivraisonResponse],
    summary="Résultats de livraison d'une notification",
    description=(
        "Tentatives de remise d'une notification par canal, sans adresse de destinataire. "
        "Exige `notifications.read` pour lire les livraisons ; sans cette permission, seule la "
        "notification du compte courant est visible (403), les autres renvoient 404. "
        "Détail : `app/notifications/routes.md`."
    ),
)
async def list_livraisons(
    notification_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LivraisonResponse]:
    """Résultats de livraison (BE-171, CA-2, CA-3, CA-4). Décision dans `consultation.py`."""
    return await consultation.lister_livraisons(
        db,
        organization_id=organization_id,
        acteur_id=current_user.id,
        notification_id=notification_id,
    )


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


@router.get(
    "/preferences",
    response_model=list[PreferenceNotificationResponse],
    summary="Préférences de notification de l'utilisateur courant",
    description="Consentements enregistrés de l'utilisateur connecté, par catégorie. Une catégorie sans ligne n'apparaît pas (aucune valeur par défaut). Détail : `app/notifications/preferences.md`.",
)
async def list_preferences(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PreferenceNotificationResponse]:
    lignes = await preferences_service.lire_preferences(
        db, organization_id=organization_id, acteur_id=current_user.id, utilisateur_id=current_user.id
    )
    return [PreferenceNotificationResponse.model_validate(ligne) for ligne in lignes]


@router.put(
    "/preferences/{categorie_code}",
    response_model=PreferenceNotificationResponse,
    summary="Modifier la préférence d'une catégorie",
    description="Enregistre le consentement de l'utilisateur connecté pour la catégorie et son horodatage. `consentement: false` vaut désinscription. Détail : `app/notifications/preferences.md`.",
)
async def update_preference(
    categorie_code: str,
    data: ModifierPreferenceRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferenceNotificationResponse:
    ligne = await preferences_service.modifier_preference(
        db,
        organization_id=organization_id,
        acteur_id=current_user.id,
        utilisateur_id=current_user.id,
        categorie_code=categorie_code,
        consentement=data.consentement,
    )
    return PreferenceNotificationResponse.model_validate(ligne)
