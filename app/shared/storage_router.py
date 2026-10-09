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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import OrganizationUser, User
from app.rbac.service import get_current_organization_id
from app.shared.file_types import EXTENSIONS_AFFICHABLES, MIME_AFFICHABLES, detecter_type, nom_de_base
from app.shared.storage import LocalFilesystemStorageBackend, StorageError, get_storage_backend

storage_router = APIRouter()

# T-014 : lecture bornée. Le serveur ne lit jamais plus de MAX+1 octets : au-delà,
# le fichier est refusé sans être chargé en entier (la lecture entière d'un
# fichier de plusieurs centaines de Mo consomme la mémoire du processus).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 Mo — limite raisonnable pour un document/photo, pas une vidéo.
THUMBNAIL_MAX_SIZE = (200, 200)

# Types MIME actifs : jamais servis tels quels depuis l'origine de l'API (XSS stockée).
# Un fichier déjà stocké avec un de ces types est servi en `attachment`, type neutre.
_MIME_ACTIFS_MARQUEURS = ("html", "svg", "xml", "javascript", "ecmascript")


@storage_router.post("/upload")
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # T-014 : l'organisation indiquée par l'en-tête doit être une organisation dont
    # l'utilisateur est membre ; sinon un fichier serait écrit dans le préfixe d'une
    # autre organisation.
    membre = await db.execute(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == current_user.id
        )
    )
    if membre.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Vous n'appartenez pas à cette organisation.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (25 Mo maximum).")

    # T-014 : liste blanche par contenu. Le nom et le Content-Type fournis par le
    # client ne comptent pas : seule la signature des octets décide.
    type_fichier = detecter_type(content)
    if type_fichier is None:
        raise HTTPException(status_code=415, detail="Type de fichier non autorisé (PDF, PNG, JPEG ou WebP uniquement).")

    backend = get_storage_backend()
    # Référence générée par le backend (uuid), extension du type détecté : le nom
    # fourni par le client n'entre jamais dans la référence de stockage.
    storage_reference = backend.upload(content, f"fichier{type_fichier.extension}", organization_id)

    thumbnail_reference: str | None = None
    if type_fichier.mime.startswith("image/"):
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
        "fileName": nom_de_base(file.filename),
        "mimeType": type_fichier.mime,
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
    #
    # T-014 : seuls PDF et images de la liste blanche sont affichés en ligne.
    # Tout le reste (y compris un HTML ou un SVG stocké avant T-014) est forcé en
    # téléchargement, avec un type neutre quand il est actif. nosniff empêche le
    # navigateur de deviner un type exécutable ; sandbox neutralise toute
    # exécution si la réponse est malgré tout rendue.
    guessed_type, _ = mimetypes.guess_type(storage_reference)
    extension = ("." + storage_reference.rsplit(".", 1)[-1].lower()) if "." in storage_reference else ""
    affichable = extension in EXTENSIONS_AFFICHABLES and (guessed_type or "") in MIME_AFFICHABLES
    if affichable:
        media_type, disposition = guessed_type, "inline"
    else:
        est_actif = guessed_type is None or any(marqueur in guessed_type for marqueur in _MIME_ACTIFS_MARQUEURS)
        media_type = "application/octet-stream" if est_actif else guessed_type
        disposition = "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{storage_reference}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
