"""Notifications d'une action opérateur (BE-144).

Table `admin_notification` : une ligne par tentative d'notification liée à une
commande opérateur (`admin_command`, BE-124). La définition nomme la clé `id` ; elle
porte ici le nom `notificationId`, comme `commandId` pour BE-124.

Règle centrale (CA-1) : l'envoi est exécuté après l'action et son échec ne l'annule
jamais. `notifier_action` ne lève donc aucune exception liée à l'envoi : il enregistre
`echec` avec un motif court (`erreur_envoi`) et rend la main. Le message brut de
l'erreur n'est ni stocké ni journalisé, pour qu'une charge utile ne fuie pas (CA-4).

Canal et destinataires : NON DÉFINIS (PH-13). La colonne `channel` reste NULL tant
que le catalogue n'est pas validé, et `recipientRef` est une référence opaque passée
par l'appelant, jamais une adresse résolue ici. L'envoyeur est injecté : ce module
n'appelle aucun canal réel.

Statuts : `envoyee` (sentAtUtc renseigné, failureReason NULL) ou `echec`
(sentAtUtc NULL, failureReason renseigné). Le module ne fait aucun commit : l'appelant
valide la transaction, comme pour les autres services du socle.

Lecture : la route `GET /api/v1/admin/commands/{command_id}/notifications` vit dans
`app.operator.notifications_router` (droits calqués sur la lecture de commande).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

logger = logging.getLogger(__name__)

STATUT_ENVOYEE = "envoyee"
STATUT_ECHEC = "echec"
# Motif stable et court : le message de l'exception n'est jamais persisté (CA-4).
MOTIF_ECHEC_ENVOI = "erreur_envoi"


class AdminNotification(Base):
    """Une tentative de notification liée à une commande opérateur (BE-144).

    `commandId` référence `admin_command.commandId`, avec suppression en cascade : une
    notification n'a pas de sens sans la commande qui l'a produite.
    """

    __tablename__ = "admin_notification"
    __table_args__ = (
        CheckConstraint("status IN ('envoyee', 'echec')", name="ck_admin_notification_status"),
        {"comment": "Notifications liées aux commandes opérateur, sans charge utile brute (BE-144)."},
    )

    notificationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commandId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_command.commandId", ondelete="CASCADE"), nullable=False, index=True,
    )
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recipientRef: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sentAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failureReason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    createdAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


async def notifier_action(
    db: AsyncSession,
    command_id: uuid.UUID,
    recipient_ref: str,
    envoyer: Callable[[], Awaitable[None]],
    *,
    channel: str | None = None,
) -> AdminNotification:
    """Tente l'envoi et enregistre le résultat, sans jamais propager l'échec d'envoi.

    `envoyer` est un appel asynchrone sans argument qui réalise l'envoi ; il lève une
    exception en cas d'échec. Toute exception est attrapée ici : c'est la garantie CA-1,
    l'action déjà réalisée ne dépend pas du canal. Seul le type de l'exception est
    journalisé, jamais son message, qui peut contenir une charge utile (CA-4).

    La ligne est ajoutée à la session et poussée (flush) ; l'appelant valide la transaction.
    """
    try:
        await envoyer()
    except Exception as exc:  # noqa: BLE001 - voulu : un canal en panne ne doit pas annuler l'action
        logger.warning("Échec d'envoi de notification de commande (%s)", type(exc).__name__)
        ligne = AdminNotification(
            commandId=command_id,
            channel=channel,
            recipientRef=recipient_ref,
            status=STATUT_ECHEC,
            sentAtUtc=None,
            failureReason=MOTIF_ECHEC_ENVOI,
            createdAtUtc=datetime.now(timezone.utc),
        )
    else:
        ligne = AdminNotification(
            commandId=command_id,
            channel=channel,
            recipientRef=recipient_ref,
            status=STATUT_ENVOYEE,
            sentAtUtc=datetime.now(timezone.utc),
            failureReason=None,
            createdAtUtc=datetime.now(timezone.utc),
        )
    db.add(ligne)
    await db.flush()
    return ligne
