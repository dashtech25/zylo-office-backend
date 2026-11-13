"""Route de lecture des notifications d'une commande opérateur (BE-144).

Route : `GET /api/v1/admin/commands/{command_id}/notifications`, montée sous
`/api/v1/admin`. Renvoie la liste des lignes `admin_notification` de la commande, par
date de création, sans charge utile brute (projection CA-4).

Droits (définition BE-144, calqués sur la lecture d'une commande, BE-124) : lecture
par l'initiateur de la commande, par un auditeur ou par un responsable de gestion de
la portée de la cible. Tout autre compte reçoit 403 (CA-2 : un agent L1 non initiateur)
et un compte d'un autre tenant reçoit 403 (CA-3). 404 si la commande n'existe pas.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.notifications.admin_notifications import AdminNotification
from app.operator.cases import ROLES_GESTION, erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.commands import AdminCommand, erreur_commande_introuvable

router = APIRouter()

# Rôles qui lisent les notifications d'une commande de leur portée, hors initiateur.
ROLES_LECTURE_NOTIFICATIONS = frozenset(ROLES_GESTION | {"auditeur"})


class NotificationResponse(BaseModel):
    """Projection d'une notification : seuls ces champs sortent, jamais de charge utile."""

    model_config = ConfigDict(from_attributes=True)

    notificationId: uuid.UUID
    commandId: uuid.UUID
    channel: str | None
    recipientRef: str
    status: str
    sentAtUtc: datetime | None
    failureReason: str | None


@router.get(
    "/commands/{command_id}/notifications",
    response_model=list[NotificationResponse],
    summary="Lire les notifications d'une commande opérateur (BE-144)",
)
async def lire_notifications_commande(
    command_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminNotification]:
    """Liste les notifications de la commande si le compte a le droit de la lire.

    L'initiateur lit toujours ; sinon il faut un rôle de lecture (auditeur, responsable
    de gestion) actif sur exactement la portée de la commande (BE-120, CA-3).
    """
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()
    if commande.actorId != current_user.id:
        roles = await roles_actifs_sur_portee(db, current_user.id, portee_du_cas(commande.tenantId))
        if not roles & ROLES_LECTURE_NOTIFICATIONS:
            raise erreur_refus()
    stmt = (
        select(AdminNotification)
        .where(AdminNotification.commandId == command_id)
        .order_by(AdminNotification.createdAtUtc, AdminNotification.notificationId)
    )
    return list((await db.execute(stmt)).scalars().all())
