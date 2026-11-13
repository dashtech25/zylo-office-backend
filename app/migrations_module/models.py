"""Modèles pour le module de migration BE-198.

Tables :
- migration_run : suivi de l'exécution d'une migration de module (BE-198).
  Champs : migrationId, state, checkpoint, lockOwner, leaseExpiresAt, startedAt, report.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String, Text, UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MigrationRun(Base):
    """Suivi de l'exécution d'une migration de module.

    État du run : pending, running, completed, failed.
    checkpoint : numéro du dernier élément complété dans la migration.
    lockOwner : nom du processus qui détient le verrou d'exécution.
    leaseExpiresAt : moment d'expiration du bail du verrou.
    startedAt : moment de démarrage du run.
    report : résumé en JSON de l'exécution (pour audit).
    """

    __tablename__ = "migration_run"

    migrationId: Mapped[uuid.UUID] = mapped_column(SA_UUID(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    checkpoint: Mapped[int] = mapped_column(default=0, nullable=False)
    lockOwner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    leaseExpiresAt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    startedAt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
