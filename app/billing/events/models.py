"""Table de réception des événements fournisseurs (BE-074).

Rôle : une ligne par événement reçu d'un fournisseur. La clé d'unicité (`provider`,
`providerEventId`) rend la réception idempotente (CA-2) : une seconde livraison du même
événement ne produit aucun nouvel effet.

`status` vaut `applique` (l'effet a été appliqué) ou `hors_ordre` (l'événement était plus
ancien que l'état confirmé et n'a pas été appliqué, CA-3). `quarantineFlag` est réservé à la
mise en quarantaine d'un événement contradictoire ; il est toujours à faux à la réception
normale. Le contenu du payload n'est pas stocké ici : seul l'identifiant est persisté.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class InboxEvent(UUIDPrimaryKeyMixin, Base):
    """Un événement fournisseur reçu, identifié par le couple (fournisseur, identifiant d'événement)."""

    __tablename__ = "inbox_event"
    __table_args__ = (
        UniqueConstraint("provider", "providerEventId", name="uq_inbox_event_provider_event"),
        CheckConstraint("status IN ('applique', 'hors_ordre')", name="ck_inbox_event_status"),
        {"comment": "Inbox : événements fournisseurs reçus, idempotents par (fournisseur, identifiant) (BE-074)."},
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    providerEventId: Mapped[str] = mapped_column(String(160), nullable=False)
    receivedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    quarantineFlag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
