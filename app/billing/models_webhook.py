"""Models pour BE-209 : Webhook PSP entrant"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin, TimestampMixin


class PSPWebhookReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reçu de webhook PSP pour déduplication et anti-rejeu.

    Responsabilités :
    - Déduplication des événements fournisseur
    - Vérification de la signature
    - Anti-rejeu par fenêtre temporelle
    - Quarantaine pour tenant inconnu
    """
    __tablename__ = "psp_webhook_receipt"
    __table_args__ = (
        UniqueConstraint("provider", "providerEventId", name="uq_psp_webhook_provider_event"),
        {"comment": "Reçu de webhook PSP pour déduplication et vérification de signature"},
    )

    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    providerEventId: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    signatureVerified: Mapped[bool] = mapped_column(nullable=False, default=False)
    payloadHash: Mapped[str] = mapped_column(String(256), nullable=False)
    receivedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processedStatus: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending, processing, processed, quarantined, failed
