"""Cas de vérification d'une organisation (BE-103).

Un cas est déposé par le propriétaire (statut `verification_pending`). Seule une décision interne
peut le faire passer à `verified` ou `rejected` ; aucune route de ce lot ne la prend. `motifInterne`
est un motif de décision réservé à l'opérateur : il n'est jamais renvoyé par l'API (CA-3).
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

STATUTS_VERIFICATION = ("verification_pending", "verification_required", "verified", "rejected")


class VerificationCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cas de vérification d'une organisation (BE-103)."""

    __tablename__ = "verification_case"
    __table_args__ = (
        CheckConstraint(
            "statut IN ('verification_pending', 'verification_required', 'verified', 'rejected')",
            name="ck_verification_case_statut",
        ),
        {"comment": "Cas de vérification d'organisation ; motif interne jamais exposé (BE-103)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    statut: Mapped[str] = mapped_column(String(32), nullable=False)
    motifInterne: Mapped[str | None] = mapped_column(Text, nullable=True)
