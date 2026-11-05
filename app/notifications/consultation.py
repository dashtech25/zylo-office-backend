"""Consultation des notifications produites par le moteur (BE-171).

Lecture seule des tables `notification` (BE-169) et `livraison` (BE-170). Aucune
écriture, aucune migration. Les routes sont dans `app/notifications/router.py`.

Isolation tenant (CA-5) : la table `notification` n'a pas de colonne de tenant (BE-169).
Le tenant d'une notification est celui de son événement source, rangé dans
`outbox_evenement.tenantId`. Une notification dont l'événement source est enregistré
pour un AUTRE tenant est donc exclue ; une notification sans événement enregistré, ou
dont l'événement est plateforme (tenant nul), reste visible à son destinataire.

Droits des livraisons (CA-3, CA-4) : ordre de décision, du plus strict au plus large.
1. notification absente, hors tenant ou sans trace -> `404` NOTIFICATION_NOT_FOUND ;
2. sans `notifications.read` : la notification du compte courant renvoie `403`
   PERMISSION_DENIED ; celle d'un autre destinataire renvoie `404` (sans révéler son
   existence) ;
3. avec `notifications.read` : lecture dans le périmètre de l'organisation active, c'est-
   à-dire pour un destinataire membre de cette organisation ; sinon `404`.
"""

import uuid

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.models import OutboxEvenement
from app.identity.models import OrganizationUser
from app.notifications.models import Livraison, Notification
from app.notifications.permissions import NOTIFICATIONS_READ
from app.rbac.service import user_has_permission
from app.shared.schemas import Page, PageMeta
from app.notifications.schemas import LivraisonResponse, NotificationResponse


def _evenement_d_un_autre_tenant(organization_id: uuid.UUID):
    """Clause : l'événement source de la notification est rattaché à un autre tenant.

    `tenantId` nul (événement plateforme) n'exclut pas la notification : SQL ne compare
    pas `NULL != x` à vrai, ce qui laisse ces lignes visibles, voulu.
    """
    return exists().where(
        and_(
            OutboxEvenement.eventId == Notification.eventId,
            OutboxEvenement.tenantId != organization_id,
        )
    )


async def lister_notifications(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    statut: str | None,
    limit: int,
    offset: int,
) -> Page:
    """Notifications du destinataire courant, plus récentes d'abord, filtrables par `statut`.

    CA-1 : seules les lignes dont `destinataireId` vaut le compte courant. CA-5 : voir la
    clause `_evenement_d_un_autre_tenant`.
    """
    stmt = select(Notification).where(
        Notification.destinataireId == user_id,
        ~_evenement_d_un_autre_tenant(organization_id),
    )
    if statut is not None:
        stmt = stmt.where(Notification.statut == statut)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    lignes = (
        await db.execute(stmt.order_by(Notification.creeAt.desc(), Notification.id.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return Page(
        data=[NotificationResponse.model_validate(ligne) for ligne in lignes],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


async def _membre_de_l_organisation(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID) -> bool:
    appartenance = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == utilisateur_id,
        )
    )
    return appartenance is not None


async def lister_livraisons(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> list[LivraisonResponse]:
    """Résultats de livraison d'une notification, par numéro de tentative croissant.

    Ordre de décision décrit dans le docstring du module (CA-3, CA-4, CA-5). Aucun champ
    de destinataire n'est renvoyé (CA-2) : `LivraisonResponse` n'en porte pas.
    """
    notification = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            ~_evenement_d_un_autre_tenant(organization_id),
        )
    )
    if notification is None:
        raise AppError("NOTIFICATION_NOT_FOUND", "Notification introuvable.", status_code=404)

    lecture_organisation = await user_has_permission(db, acteur_id, organization_id, NOTIFICATIONS_READ)
    if not lecture_organisation:
        if notification.destinataireId != acteur_id:
            raise AppError("NOTIFICATION_NOT_FOUND", "Notification introuvable.", status_code=404)
        raise AppError(
            "PERMISSION_DENIED",
            f"Permission manquante : {NOTIFICATIONS_READ}.",
            status_code=403,
        )

    if not await _membre_de_l_organisation(db, organization_id, notification.destinataireId):
        raise AppError("NOTIFICATION_NOT_FOUND", "Notification introuvable.", status_code=404)

    lignes = (
        await db.execute(
            select(Livraison)
            .where(Livraison.notificationId == notification_id)
            .order_by(Livraison.tentativeNo.asc())
        )
    ).scalars().all()
    return [LivraisonResponse.model_validate(ligne) for ligne in lignes]
