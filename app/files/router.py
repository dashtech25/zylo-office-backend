"""Routes du module Files — extraites de `app/modules/zylo_liquid/router.py`
(2026-09-15, Phase 1). Montées sous le même préfixe `/zylo-liquid` que
précédemment (voir `app/api/v1/router.py`) : le déplacement du code entre
modules Python ne doit jamais casser une URL déjà consommée par le
frontend — seule la Phase où le frontend adopte ses propres préfixes par
domaine (hors scope de cette migration, voir CLAUDE.md) changera ça."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.files import service
from app.files.schemas import (
    CreateDocumentLinkRequest,
    CreateDocumentRequest,
    DocumentCountsResponse,
    DocumentDownloadUrlResponse,
    DocumentLinkResponse,
    DocumentResponse,
)
from app.identity.models import User
from app.rbac.service import get_current_organization_id

router = APIRouter()


@router.post("/documents", response_model=DocumentResponse, status_code=201, summary="Référencer un nouveau document")
async def create_document(
    data: CreateDocumentRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Enregistre les métadonnées d'un fichier déjà uploadé (voir
    `POST /storage/upload` pour l'upload des octets lui-même) — optionnellement
    lié à une entité dès la création via `linkedEntityType`/`linkedEntityId`."""
    return await service.create_document(db, organization_id, current_user.id, data)


@router.post("/document-links", response_model=DocumentLinkResponse, status_code=201, summary="Lier un document existant à une entité supplémentaire")
async def create_document_link(
    data: CreateDocumentLinkRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentLinkResponse:
    return await service.create_document_link(db, organization_id, current_user.id, data)


@router.get("/documents/by-entity", response_model=list[DocumentResponse], summary="Lister les documents attachés à une entité")
async def list_documents_for_entity(
    linkedEntityType: str,
    linkedEntityId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    return await service.list_document_links_for_entity(db, organization_id, current_user.id, linkedEntityType, linkedEntityId)


@router.get("/documents/counts-by-entity", response_model=DocumentCountsResponse, summary="Compter les documents de plusieurs entités en un seul appel")
async def count_documents_for_entities(
    linkedEntityType: str,
    linkedEntityIds: str,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentCountsResponse:
    """`linkedEntityIds` : identifiants séparés par des virgules (audit
    performance — un seul appel réseau au lieu d'un par ligne de tableau
    dans les écrans Réglementation/Fournisseurs)."""
    ids = [uuid.UUID(raw) for raw in linkedEntityIds.split(",") if raw.strip()]
    counts = await service.count_documents_by_entity(db, organization_id, current_user.id, linkedEntityType, ids)
    return DocumentCountsResponse(counts=counts)


@router.delete("/documents/{document_id}", response_model=DocumentResponse, summary="Supprimer un document (suppression logique)")
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Suppression logique uniquement (`deletedAt`) — rétention 90 jours
    avant purge physique (tâche planifiée hors périmètre applicatif)."""
    return await service.delete_document(db, organization_id, current_user.id, document_id)


@router.get("/documents/{document_id}/download-url", response_model=DocumentDownloadUrlResponse, summary="Obtenir un lien de téléchargement signé et temporaire")
async def get_document_download_url(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownloadUrlResponse:
    url = await service.get_document_download_url(db, organization_id, current_user.id, document_id)
    return DocumentDownloadUrlResponse(url=url)
