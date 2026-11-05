"""Modèles de la sortie de tenant (BE-246).

`tenant_exit_requests` garde une ligne par sortie : demandeur, approbateur, état, holds actifs
au moment de la décision, étapes et attestation. `legal_holds` garde les holds posés sur un
tenant : tant qu'un hold existe pour le tenant, la sortie n'efface rien.

Les deux tables sont des preuves : elles ne sont jamais effacées par une sortie (voir
service.py, TABLES_PROTEGEES).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

# Terminée : données effacées, attestation émise. Tenue : un hold actif a empêché tout effacement.
ETAT_TERMINEE = "terminee"
ETAT_TENUE = "tenue"


class TenantExitRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une demande de sortie de tenant, avec sa décision et son attestation."""

    __tablename__ = "tenant_exit_requests"
    __table_args__ = (
        CheckConstraint(f"etat IN ('{ETAT_TERMINEE}', '{ETAT_TENUE}')", name="ck_tenant_exit_requests_etat"),
        {"comment": "Demande de sortie d'un tenant : approbation, holds, étapes et attestation (BE-246)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    demandeur: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    approbateur: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    motif: Mapped[str] = mapped_column(String(500), nullable=False)
    etat: Mapped[str] = mapped_column(String(16), nullable=False)
    holds: Mapped[list] = mapped_column(JSON, nullable=False)  # identifiants des holds actifs à la décision
    etapes: Mapped[list] = mapped_column(JSON, nullable=False)
    attestation: Mapped[dict] = mapped_column(JSON, nullable=False)
    decideLe: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LegalHold(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un hold posé sur un tenant : motif, décideur et date de pose."""

    __tablename__ = "legal_holds"
    __table_args__ = ({"comment": "Holds juridiques posés sur un tenant ; un hold actif bloque la sortie (BE-246)."},)

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    motif: Mapped[str] = mapped_column(String(500), nullable=False)
    decideur: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    poseLe: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
