"""Modèles des jobs d'import et d'export (BE-213).

Table `job` : une ligne par demande de job. L'isolation se fait par `tenantId` : toute lecture
passe par ce tenant, un job d'un autre tenant est indiscernable d'un job absent (404).

`state` suit la machine : queued -> running -> succeeded | failed ; queued | running -> cancelled ;
succeeded -> expired (échéance `expiresAt` dépassée). `idempotencyKey` est unique par tenant :
un second POST avec la même clé renvoie le job existant sans en créer un autre (CA-2).

`filePointer` est la référence opaque du fichier produit, dans le backend de stockage
(app/shared/storage.py). Table `job_error_report` : une ligne par erreur de traitement, rattachée
au job (ligne, code, message).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

ETAT_QUEUED = "queued"
ETAT_RUNNING = "running"
ETAT_SUCCEEDED = "succeeded"
ETAT_FAILED = "failed"
ETAT_CANCELLED = "cancelled"
ETAT_EXPIRED = "expired"
ETATS = (ETAT_QUEUED, ETAT_RUNNING, ETAT_SUCCEEDED, ETAT_FAILED, ETAT_CANCELLED, ETAT_EXPIRED)


class Job(TimestampMixin, Base):
    """Job d'import ou d'export d'un tenant (BE-213)."""

    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("tenantId", "idempotencyKey", name="uq_job_tenant_idempotencyKey"),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')",
            name="ck_job_state",
        ),
        {"comment": "Job d'import ou d'export d'un tenant, rejouable par clé d'idempotence (BE-213)."},
    )

    jobId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True)
    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    manifestSchemaVersion: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=ETAT_QUEUED, server_default=ETAT_QUEUED)
    idempotencyKey: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filePointer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expiresAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobErrorReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Erreur de traitement d'un job (ligne, code, message), pour le rapport d'erreurs (BE-213)."""

    __tablename__ = "job_error_report"
    __table_args__ = ({"comment": "Rapport d'erreurs d'un job d'import ou d'export (BE-213)."},)

    jobId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job.jobId", ondelete="CASCADE"), nullable=False, index=True
    )
    ligne: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
