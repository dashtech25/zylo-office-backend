"""Modèle de l'export de données asynchrone du portail (BE-117).

Table `export_job` : une ligne par demande d'export d'une organisation. Cycle de vie :
`export_requested` (demande acceptée, traitement pas encore fait) -> `ready` (contenu
disponible, `expiresAt` fixé à partir de la configuration) -> `expired` (échéance passée ; le
contenu est purgé, il ne subsiste aucune copie au-delà de `expiresAt`).

Le contenu est porté par la ligne tant que l'export est prêt ; il n'est écrit sur aucun fichier.
Table distincte de `export_jobs` (BE-243) et de `job` (BE-213) : les trois capacités d'export
coexistent sans partager de schéma.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

STATUT_REQUETE = "export_requested"
STATUT_PRET = "ready"
STATUT_EXPIRE = "expired"
STATUTS = (STATUT_REQUETE, STATUT_PRET, STATUT_EXPIRE)


class PortailExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Demande d'export de données d'une organisation, à durée de vie limitée (BE-117).

    `perimetre` : aujourd'hui toujours `membres` (liste des membres de l'organisation).
    `contenu` : enregistrements JSON, NULL tant que l'export n'est pas prêt et après purge.
    `expiresAt` : NULL tant que l'export n'est pas prêt ; jamais fixé sans durée configurée."""

    __tablename__ = "export_job"
    __table_args__ = (
        CheckConstraint(
            "statut IN ('export_requested', 'ready', 'expired')",
            name="ck_export_job_statut",
        ),
        {"comment": "Demande d'export de données asynchrone du portail, à durée de vie limitée (BE-117)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    requestedBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    perimetre: Mapped[str] = mapped_column(String(32), nullable=False)
    statut: Mapped[str] = mapped_column(String(32), nullable=False, server_default=STATUT_REQUETE)
    contenu: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expiresAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
