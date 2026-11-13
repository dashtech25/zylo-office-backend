"""Modèle du job d'export de données (BE-243).

Table `export_jobs` : une ligne par demande. `contenu` porte les enregistrements exportés
jusqu'à l'expiration ; la purge (app/exports/service.py::purger_exports_expires) le remet à
NULL dès que `expireAt` est atteint, pour qu'aucune copie ne subsiste au-delà de la durée
de vie (CA-5). Aucun fichier n'est écrit sur disque.

`empreinte` est le SHA-256 de la forme canonique du contenu, calculé à la création : il
permet à l'appelant de vérifier l'intégrité de ce qu'il télécharge.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

STATUT_PRET = "pret"
STATUT_EXPIRE = "expire"


class ExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job d'export de données d'une organisation.

    `perimetre` : {"type": "tenant"} ou {"type": "sujet", "sujetId": ...}, tel que demandé.
    `statut` : valeur stockée, mise à `expire` par la purge ; le statut lu par l'API tient
    aussi compte de `expireAt`, pour qu'un job échu soit vu expiré même avant la purge.
    `contenu` : liste d'enregistrements JSON, NULL après purge."""

    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(f"statut IN ('{STATUT_PRET}', '{STATUT_EXPIRE}')", name="ck_export_jobs_statut"),
        CheckConstraint("length(empreinte) = 64", name="ck_export_jobs_empreinte_sha256"),
        {"comment": "Job d'export de données par sujet ou tenant, à durée de vie limitée (BE-243)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    demandeur: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    perimetre: Mapped[dict] = mapped_column(JSON, nullable=False)
    statut: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUT_PRET)
    expireAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    empreinte: Mapped[str] = mapped_column(String(64), nullable=False)
    contenu: Mapped[list | None] = mapped_column(JSON, nullable=True)
