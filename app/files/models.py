"""Module Files — capacité partagée (2026-09-15, extraction Phase 1 de la
migration monolithe modulaire, voir plan-migration/architecture-migration.md
dans le repo prototype). Déplacé tel quel depuis
`app/modules/zylo_liquid/models.py` (processus-double-sources-verite,
Phase 5 §6, Bloc 5) — noms de tables Postgres inchangés (`zyloLiquidDocument`/
`zyloLiquidDocumentLink`), aucune migration de données pour ce déplacement.

Un fichier physique stocké une seule fois, référencé par plusieurs entités
via `DocumentLink`, jamais dupliqué. Le stockage effectif des octets
(S3/disque) est hors périmètre de ce modèle — `storageReference` est une
référence opaque fournie par l'appelant (voir `app/shared/storage.py`,
capacité de stockage bas niveau, déjà partagée avant cette migration),
jamais interprétée ici.

`linkedEntityType`/`linkedEntityId` sont volontairement de simples colonnes
(pas de ForeignKey) — Files ne doit jamais connaître les tables des modules
qui l'utilisent (Liquid, futur Tank/CRM...). C'est ce découplage déjà en
place qui a rendu ce module le premier candidat à l'extraction."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zyloLiquidDocument"
    __table_args__ = (
        CheckConstraint("\"sensitivityLevel\" IN ('normal','restreint')", name="ck_zlDocument_sensitivityLevel"),
        {"comment": "Fichier physique référencé une seule fois — jamais dupliqué (Phase 5 §6, association logique)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    storageReference: Mapped[str] = mapped_column(String(500), nullable=False)
    fileName: Mapped[str] = mapped_column(String(255), nullable=False)
    mimeType: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uploadedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False)
    sensitivityLevel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    supersedesDocumentId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDocument.id", ondelete="SET NULL"), nullable=True)
    deletedAt: Mapped[datetime | None] = mapped_column(nullable=True)


class DocumentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Table de liaison polymorphe — plusieurs `DocumentLink` peuvent
    pointer vers le même `Document` (Phase 5 §6) : c'est exactement
    l'association logique décidée par le commanditaire, jamais une copie
    physique par entité liée."""

    __tablename__ = "zyloLiquidDocumentLink"
    __table_args__ = (
        UniqueConstraint("documentId", "linkedEntityType", "linkedEntityId", name="uq_zlDocumentLink_document_entity"),
        {"comment": "Association document <-> entité — plusieurs liens possibles vers un même Document, jamais de duplication."},
    )

    documentId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zyloLiquidDocument.id", ondelete="RESTRICT"), nullable=False, index=True)
    linkedEntityType: Mapped[str] = mapped_column(String(40), nullable=False)
    linkedEntityId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
