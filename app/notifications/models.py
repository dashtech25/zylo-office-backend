"""Modèle du module Notifications (capacité partagée, core — au même titre
qu'`app/alerts/`, jamais spécifique à un module métier) : abonnements Web
Push navigateur (RFC 8030). Un utilisateur peut avoir plusieurs abonnements
actifs (plusieurs navigateurs/appareils) — jamais un seul par utilisateur,
donc pas de contrainte d'unicité sur `userId` seul."""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
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
