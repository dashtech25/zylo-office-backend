"""Endpoints du service de stockage générique (Phase 5 §2 de la mission
« vente-maintenant-reglementation ») — expose l'upload et le téléchargement
signé, réutilisable par tout module Zylo Office (classification "techniquement
partagée", Phase 3 §1 du plan de mission). La création de `Document`
(métadonnées métier) reste dans `zylo_liquid` — cet endpoint ne fait que
déplacer des octets, jamais de logique métier."""

import io
import mimetypes
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.service import get_current_organization_id
from app.shared.storage import LocalFilesystemStorageBackend, StorageError, get_storage_backend
from sqlalchemy.ext.asyncio import AsyncSession

storage_router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 Mo — limite raisonnable pour un document/photo, pas une vidéo.
THUMBNAIL_MAX_SIZE = (200, 200)


@storage_router.post("/upload")
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (25 Mo maximum).")
    backend = get_storage_backend()
    storage_reference = backend.upload(content, file.filename or "fichier", organization_id)

    thumbnail_reference: str | None = None
    if (file.content_type or "").startswith("image/"):
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(content))
            image.thumbnail(THUMBNAIL_MAX_SIZE)
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG")
            thumbnail_reference = backend.upload(buf.getvalue(), "thumbnail.jpg", organization_id)
        except Exception:
            # La miniature est un confort d'affichage, jamais bloquant pour
            # l'upload lui-même (Phase 5 §6 du plan de mission) — un format
            # d'image non supporté par Pillow ne doit pas faire échouer
            # l'upload du fichier original.
            thumbnail_reference = None

    return {
        "storageReference": storage_reference,
        "thumbnailReference": thumbnail_reference,
        "fileName": file.filename,
        "mimeType": file.content_type,
    }


@storage_router.get("/local/{storage_reference}")
async def download_local_file(storage_reference: str, expires: int, signature: str) -> Response:
    """Sert un fichier stocké par le backend local, uniquement avec une
    signature valide et non expirée (Phase 5 §2.2 du plan de mission :
    jamais de lien public permanent). Sans objet pour le backend S3/MinIO —
    les URLs signées de ce backend pointent directement vers le stockage
    objet, jamais vers cette route."""
    backend = get_storage_backend()
    if not isinstance(backend, LocalFilesystemStorageBackend):
        raise HTTPException(status_code=404, detail="Route sans objet pour le backend de stockage actif.")
    if not backend.verify_signed_url(storage_reference, expires, signature):
        raise HTTPException(status_code=403, detail="Lien de téléchargement invalide ou expiré.")
    try:
        content = backend.read(storage_reference)
    except StorageError:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    # Type MIME déduit de l'extension conservée dans la référence de
    # stockage (mission « bon de commande + aperçu/partage », 2026-09-10) —
    # sans cela, le navigateur reçoit toujours application/octet-stream et
    # refuse d'afficher un PDF/une image en ligne (iframe/<img>), forçant un
    # téléchargement même quand un aperçu est demandé.
    guessed_type, _ = mimetypes.guess_type(storage_reference)
    return Response(content=content, media_type=guessed_type or "application/octet-stream")
