"""Tables `incidents` et `incident_events` : gestion des incidents d'exploitation (BE-247).

- `incidents` : un incident a un propriétaire, un état et un horodatage obligatoires
  (CA-1). `tenantId` est nul pour un incident de plateforme ; il désigne le tenant
  concerné sinon, sans jamais porter le contenu de ce tenant (CA-3).
- `incident_events` : chronologie append-only (CA-2). Une ligne ne se modifie ni ne
  se supprime : le trigger posé par la migration de BE-247 refuse UPDATE et DELETE.
  `sequence` est une identité de base qui fixe l'ordre de la chronologie, même quand
  plusieurs événements partagent la même horloge de transaction.

Les valeurs de `severity` et `state` sont contraintes en base, pas seulement dans le
service, pour qu'une écriture directe ne puisse pas contourner le vocabulaire.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin

SEVERITES_INCIDENT = ("critical", "high", "medium", "low")
# Vocabulaire d'état : NON DÉFINI dans la définition BE-247 ; retenu ici (QE-BE247-02).
ETATS_INCIDENT = ("ouvert", "en_cours", "resolu", "cloture")
ETAT_INITIAL = "ouvert"


class Incident(UUIDPrimaryKeyMixin, Base):
    """Incident d'exploitation : sévérité, propriétaire, état, horodatage, tenant éventuel."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical','high','medium','low')", name="ck_incidents_severity"
        ),
        CheckConstraint(
            "state IN ('ouvert','en_cours','resolu','cloture')", name="ck_incidents_state"
        ),
        {"comment": "Incidents d'exploitation : owner, état et horodatage obligatoires (BE-247)."},
    )

    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # Équipe ou rôle nommé responsable de l'incident ; obligatoire (CA-1).
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    occurredAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Tenant concerné, nul pour un incident de plateforme. Pas de colonne de contenu tenant.
    tenantId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )


class IncidentEvent(UUIDPrimaryKeyMixin, Base):
    """Entrée de chronologie d'un incident, ajout seul (CA-2)."""

    __tablename__ = "incident_events"
    __table_args__ = (
        {"comment": "Chronologie append-only des incidents ; UPDATE et DELETE refusés par trigger (BE-247)."},
    )

    incidentId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, index=True
    )
    # Ordre de la chronologie, attribué par la base.
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    eventType: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    actorUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    # Lien vers l'entrée du journal d'audit (BE-227), sans clé étrangère : le journal
    # reste autonome et ne bloque jamais la chronologie.
    auditEventId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurredAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
