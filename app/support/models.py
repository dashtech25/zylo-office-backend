"""Modèle `acces_support` (BE-262) : accès accordé à un membre du support.

Une ligne donne à `supportUserId` un accès à UNE organisation, dans une fenêtre
`[debutUtc, finUtc[`, avec un `mode` (`lecture` par défaut). `approbationId`
reste nul : la double approbation n'est pas implémentée en BE-262 (QE-FON-06).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class AccesSupport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Accès support à une organisation, lecture seule par défaut.

    `creeParUserId` garde l'auteur de l'octroi pour l'audit. `finUtc` borne
    l'accès : au-delà, `support/service.py` le refuse sans qu'aucune tâche de
    nettoyage soit nécessaire."""

    __tablename__ = "acces_support"
    __table_args__ = {"comment": "Accès support à une organisation : lecture seule par défaut, justifié, daté (BE-262)."}

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    supportUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    creeParUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="lecture", server_default="lecture")
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    debutUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approbationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
