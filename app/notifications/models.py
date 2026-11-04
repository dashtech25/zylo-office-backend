"""Modèles de la capacité Notifications partagée : abonnements Web Push et
éléments d'inbox explicitement adressés. Aucun type de notification ni
producteur produit n'est défini dans ce module.

Tables : `notificationPushSubscription` (PushSubscription) et
`notification_inbox_item` (NotificationInboxItem). Les tables sont listées
dans l'inventaire des données (`app/data_inventory/registre.py`) : tout
renommage de table doit l'y reporter, sinon `tests/test_inventaire_donnees_be242.py`
échoue. Les noms de table suivent la règle de la tâche BE-037 : snake_case
pour les tables décidées depuis, camelCase pour les plus anciennes."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class PushSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un abonnement Web Push par (utilisateur, endpoint navigateur) —
    `endpoint` est l'URL unique fournie par le navigateur au moment de
    `PushManager.subscribe()`, jamais réutilisée entre deux
    navigateurs/appareils différents (contrainte d'unicité dessus, pas sur
    `userId`)."""

    __tablename__ = "notificationPushSubscription"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_notificationPushSubscription_endpoint"),
        {"comment": "Abonnement Web Push navigateur (RFC 8030) — module Notifications, 2026-09-20."},
    )

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # Clés fournies par le navigateur à l'abonnement (chiffrement du payload
    # push côté serveur, standard Web Push) — jamais générées ici.
    p256dhKey: Mapped[str] = mapped_column(String(255), nullable=False)
    authKey: Mapped[str] = mapped_column(String(255), nullable=False)
    userAgent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class NotificationInboxItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message interne explicitement adressé à un membre d'organisation.

    Table `notification_inbox_item` (snake_case, décision BE-037 ; renommée par
    la révision f5a6b7c8d9e0). Les index et la contrainte d'unicité gardent
    leurs noms camelCase d'origine, référencés par le service d'insertion.

    Idempotence : un même événement source ne produit qu'un item par
    destinataire (contrainte `uq_notificationInboxItem_event_recipient` sur
    organisation, destinataire, type et identifiant d'événement).

    Le stockage ne choisit ni catégorie produit ni canal de livraison. Aucun
    producteur métier n'est branché tant que le catalogue d'événements PH-13
    et la frontière Notifications/Alertes (ARC-007) ne sont pas validés.
    """

    __tablename__ = "notification_inbox_item"
    __table_args__ = (
        UniqueConstraint(
            "organizationId", "recipientUserId", "sourceEventType", "sourceEventId",
            name="uq_notificationInboxItem_event_recipient",
        ),
        Index("ix_notificationInboxItem_recipient_created", "organizationId", "recipientUserId", "createdAt"),
        Index("ix_notificationInboxItem_recipient_read", "organizationId", "recipientUserId", "readAt"),
        {"comment": "Notification in-app explicitement adressée; aucun canal ni rétention automatisée implicite."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    recipientUserId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    # Clé d'idempotence de l'événement source, fournie par un producteur
    # interne de confiance; aucun endpoint HTTP client ne peut créer d'item.
    sourceEventType: Mapped[str] = mapped_column(String(80), nullable=False)
    sourceEventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    readAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
