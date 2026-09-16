"""Service du module Files — capacité partagée, extraite de
`app/modules/zylo_liquid/service.py` (2026-09-15, Phase 1 de la migration
monolithe modulaire). Logique inchangée, seul l'emplacement bouge — voir
`plan-migration/architecture-migration.md` dans le repo prototype pour le
plan complet.

Point d'entrée public de ce module : tout appelant externe (aujourd'hui
`zylo_liquid`, demain un éventuel Tank/CRM) passe UNIQUEMENT par les
fonctions de ce fichier, jamais par un accès direct à `app.files.models` —
contrat renforcé par `import-linter` (voir `.importlinter` à la racine)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.files.models import Document, DocumentLink
from app.files.permissions import DOCUMENT_CREATE, DOCUMENT_DELETE, DOCUMENT_READ, DOCUMENT_READ_SENSITIVE
from app.files.schemas import CreateDocumentLinkRequest, CreateDocumentRequest, DocumentLinkResponse, DocumentResponse
from app.rbac.service import user_has_permission


async def _check_org_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)


async def create_document_for_trusted_caller(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    storage_reference: str,
    file_name: str,
    mime_type: str | None,
    sensitivity_level: str = "normal",
    linked_entity_type: str | None = None,
    linked_entity_id: uuid.UUID | None = None,
) -> DocumentResponse:
    """Variante de `create_document` sans le contrôle `DOCUMENT_CREATE` —
    réservée aux appelants qui ont déjà vérifié leur propre permission sur
    l'action métier qui produit ce document (ex. générer le PDF d'un bon
    de commande n'exige que `PURCHASE_ORDER_MANAGE`, jamais en plus
    `DOCUMENT_CREATE` : ce n'est pas un upload libre, c'est un document
    dérivé d'une action déjà autorisée). N'appeler que depuis un contexte
    où ce raisonnement a déjà été fait — jamais comme raccourci générique."""
    document = Document(
        organizationId=organization_id,
        storageReference=storage_reference,
        fileName=file_name,
        mimeType=mime_type,
        uploadedByUserId=actor_user_id,
        sensitivityLevel=sensitivity_level,
    )
    db.add(document)
    await db.flush()
    if linked_entity_type is not None and linked_entity_id is not None:
        db.add(DocumentLink(documentId=document.id, linkedEntityType=linked_entity_type, linkedEntityId=linked_entity_id))
    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document)


async def create_document(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateDocumentRequest) -> DocumentResponse:
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_CREATE)
    document = Document(
        organizationId=organization_id,
        storageReference=data.storageReference,
        fileName=data.fileName,
        mimeType=data.mimeType,
        uploadedByUserId=actor_user_id,
        sensitivityLevel=data.sensitivityLevel,
        supersedesDocumentId=data.supersedesDocumentId,
    )
    db.add(document)
    await db.flush()
    if data.linkedEntityType is not None and data.linkedEntityId is not None:
        db.add(DocumentLink(documentId=document.id, linkedEntityType=data.linkedEntityType, linkedEntityId=data.linkedEntityId))
    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document)


async def create_document_link(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateDocumentLinkRequest) -> DocumentLinkResponse:
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_CREATE)
    document = await db.get(Document, data.documentId)
    if document is None or document.organizationId != organization_id:
        raise AppError(code="document_not_found", message="Document introuvable.", status_code=404)
    existing = await db.execute(
        select(DocumentLink).where(
            DocumentLink.documentId == data.documentId,
            DocumentLink.linkedEntityType == data.linkedEntityType,
            DocumentLink.linkedEntityId == data.linkedEntityId,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="document_link_already_exists", message="Ce document est déjà lié à cette entité.", status_code=409)
    link = DocumentLink(documentId=data.documentId, linkedEntityType=data.linkedEntityType, linkedEntityId=data.linkedEntityId)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return DocumentLinkResponse.model_validate(link)


async def list_document_links_for_entity(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, linked_entity_type: str, linked_entity_id: uuid.UUID) -> list[DocumentResponse]:
    """Retourne directement les `Document` liés (pas les lignes de liaison
    elles-mêmes) : l'appelant veut voir les fichiers attachés à SON entité,
    jamais la mécanique de liaison sous-jacente. Exclut les documents
    supprimés logiquement (Phase 5 §5 du plan de mission) et, sauf
    permission `readSensitive`, les documents marqués 'restreint' (Phase 5
    §4 / Phase 6 §5.1 du plan de mission)."""
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_READ)
    can_read_sensitive = await user_has_permission(db, actor_user_id, organization_id, DOCUMENT_READ_SENSITIVE)
    stmt = (
        select(Document)
        .join(DocumentLink, DocumentLink.documentId == Document.id)
        .where(
            Document.organizationId == organization_id,
            Document.deletedAt.is_(None),
            DocumentLink.linkedEntityType == linked_entity_type,
            DocumentLink.linkedEntityId == linked_entity_id,
        )
        .order_by(Document.createdAt.desc())
    )
    if not can_read_sensitive:
        stmt = stmt.where(Document.sensitivityLevel != "restreint")
    result = await db.execute(stmt)
    return [DocumentResponse.model_validate(r) for r in result.scalars().all()]


async def count_documents_by_entity(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, linked_entity_type: str, linked_entity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Nombre de pièces jointes pour plusieurs entités en UNE requête —
    remplace un `listDocumentsByEntity` par ligne de tableau (audit
    performance : un écran Réglementation/Fournisseurs avec N lignes
    faisait N+1 requêtes vers une base parfois distante). Un identifiant
    absent du résultat n'a simplement aucun document (jamais une erreur)."""
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_READ)
    if not linked_entity_ids:
        return {}
    can_read_sensitive = await user_has_permission(db, actor_user_id, organization_id, DOCUMENT_READ_SENSITIVE)
    stmt = (
        select(DocumentLink.linkedEntityId, func.count())
        .select_from(DocumentLink)
        .join(Document, Document.id == DocumentLink.documentId)
        .where(
            Document.organizationId == organization_id,
            Document.deletedAt.is_(None),
            DocumentLink.linkedEntityType == linked_entity_type,
            DocumentLink.linkedEntityId.in_(linked_entity_ids),
        )
        .group_by(DocumentLink.linkedEntityId)
    )
    if not can_read_sensitive:
        stmt = stmt.where(Document.sensitivityLevel != "restreint")
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def get_document_download_url(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """Lien signé et temporaire (`StorageBackend.get_download_url`, déjà
    construit pour cet usage exact côté service générique de stockage
    `app/shared/storage.py`) — jamais un lien public permanent. Un document
    'restreint' exige `DOCUMENT_READ_SENSITIVE`, même contrôle que la liste
    par entité."""
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_READ)
    document = await db.get(Document, document_id)
    if document is None or document.organizationId != organization_id or document.deletedAt is not None:
        raise AppError(code="document_not_found", message="Document introuvable.", status_code=404)
    if document.sensitivityLevel == "restreint":
        can_read_sensitive = await user_has_permission(db, actor_user_id, organization_id, DOCUMENT_READ_SENSITIVE)
        if not can_read_sensitive:
            raise AppError(code="permission_denied", message=f"Permission manquante : {DOCUMENT_READ_SENSITIVE}.", status_code=403)
    from app.shared.storage import get_storage_backend

    backend = get_storage_backend()
    return backend.get_download_url(document.storageReference)


async def delete_document(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, document_id: uuid.UUID) -> DocumentResponse:
    await _check_org_scope(db, organization_id, actor_user_id, DOCUMENT_DELETE)
    document = await db.get(Document, document_id)
    if document is None or document.organizationId != organization_id:
        raise AppError(code="document_not_found", message="Document introuvable.", status_code=404)
    document.deletedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    await record_audit_event(
        db, organization_id, actor_user_id,
        action="zyloLiquid.document.delete", entity_type="Document", entity_id=document.id,
        summary=f"Suppression logique du document {document.fileName} (rétention 90 jours avant purge).",
    )
    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document)
