"""Service générique de stockage documentaire — mission
« vente-maintenant-reglementation », Phase 5 §2 : aucun module métier
n'accède au stockage directement, tout passe par `upload`/`get_download_url`/
`delete` ci-dessous (même discipline que `record_audit_event`, jamais un
accès dispersé). Deux implémentations d'un même contrat :

- `LocalFilesystemStorageBackend` : par défaut (STORAGE_BACKEND=local),
  fonctionnelle sans aucune dépendance externe — utile en développement et
  dans tout environnement sans MinIO/S3 disponible.
- `S3CompatibleStorageBackend` : cible de production retenue en Phase 5
  (MinIO auto-hébergé, compatible S3 — STORAGE_BACKEND=s3). `boto3` est
  importé paresseusement : son absence n'empêche jamais le démarrage de
  l'application tant que ce backend n'est pas sélectionné.

URLs de téléchargement toujours signées et temporaires (Phase 5 §2.2 : un
lien public permanent contournerait le contrôle de permission par
document) — implémenté ici via HMAC-SHA256 + expiration, sans dépendance
externe (`itsdangerous` indisponible dans cet environnement)."""

import hashlib
import hmac
import io
import os
import time
import uuid
from abc import ABC, abstractmethod

from app.core.config import settings


class StorageError(Exception):
    pass


class StorageBackend(ABC):
    @abstractmethod
    def upload(self, file_bytes: bytes, file_name: str, organization_id: uuid.UUID) -> str:
        """Retourne la `storageReference` opaque à persister sur `Document`."""

    @abstractmethod
    def get_download_url(self, storage_reference: str, ttl_seconds: int | None = None) -> str:
        """URL signée et temporaire — jamais un lien public permanent."""

    @abstractmethod
    def delete(self, storage_reference: str) -> None:
        """Suppression physique — n'est appelée qu'à la purge différée
        (90 jours après suppression logique, Phase 5 §5), jamais au moment
        de `Document.deletedAt`."""

    @abstractmethod
    def read(self, storage_reference: str) -> bytes:
        """Lecture directe des octets — utilisée pour la génération de
        miniature (Phase 5 §6), pas pour servir un téléchargement (qui
        passe par `get_download_url`)."""


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class LocalFilesystemStorageBackend(StorageBackend):
    def __init__(self, root: str, signing_secret: str):
        self._root = root
        self._signing_secret = signing_secret
        os.makedirs(self._root, exist_ok=True)

    def _path_for(self, storage_reference: str) -> str:
        # storage_reference ne contient jamais de séparateur de chemin —
        # généré par ce backend uniquement (uuid + extension), jamais fourni
        # par l'appelant sans validation.
        safe = storage_reference.replace("/", "_").replace("\\", "_").replace("..", "_")
        return os.path.join(self._root, safe)

    def upload(self, file_bytes: bytes, file_name: str, organization_id: uuid.UUID) -> str:
        extension = os.path.splitext(file_name)[1][:20]
        storage_reference = f"{organization_id}_{uuid.uuid4().hex}{extension}"
        with open(self._path_for(storage_reference), "wb") as f:
            f.write(file_bytes)
        return storage_reference

    def get_download_url(self, storage_reference: str, ttl_seconds: int | None = None) -> str:
        ttl = ttl_seconds or settings.STORAGE_SIGNED_URL_TTL_SECONDS
        expires_at = int(time.time()) + ttl
        signature = _sign(f"{storage_reference}:{expires_at}", self._signing_secret)
        return f"/api/v1/storage/local/{storage_reference}?expires={expires_at}&signature={signature}"

    def verify_signed_url(self, storage_reference: str, expires: int, signature: str) -> bool:
        if int(time.time()) > expires:
            return False
        expected = _sign(f"{storage_reference}:{expires}", self._signing_secret)
        return hmac.compare_digest(expected, signature)

    def delete(self, storage_reference: str) -> None:
        path = self._path_for(storage_reference)
        if os.path.exists(path):
            os.remove(path)

    def read(self, storage_reference: str) -> bytes:
        path = self._path_for(storage_reference)
        if not os.path.exists(path):
            raise StorageError(f"Fichier introuvable pour la référence {storage_reference}.")
        with open(path, "rb") as f:
            return f.read()


class S3CompatibleStorageBackend(StorageBackend):
    """Cible de production (Phase 5 §2 : MinIO auto-hébergé, compatible S3).
    `boto3` importé à l'usage seulement — un environnement sans MinIO
    disponible reste fonctionnel avec STORAGE_BACKEND=local (défaut)."""

    def __init__(self, bucket: str, endpoint_url: str | None, access_key: str | None, secret_key: str | None, region: str):
        try:
            import boto3
        except ImportError as exc:
            raise StorageError("boto3 n'est pas installé — nécessaire pour STORAGE_BACKEND=s3 (voir requirements.txt).") from exc
        self._bucket = bucket
        self._client = boto3.client(
            "s3", endpoint_url=endpoint_url, aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region,
        )
        try:
            self._client.head_bucket(Bucket=bucket)
        except Exception:
            self._client.create_bucket(Bucket=bucket)

    def upload(self, file_bytes: bytes, file_name: str, organization_id: uuid.UUID) -> str:
        extension = os.path.splitext(file_name)[1][:20]
        key = f"{organization_id}/{uuid.uuid4().hex}{extension}"
        self._client.upload_fileobj(io.BytesIO(file_bytes), self._bucket, key)
        return key

    def get_download_url(self, storage_reference: str, ttl_seconds: int | None = None) -> str:
        ttl = ttl_seconds or settings.STORAGE_SIGNED_URL_TTL_SECONDS
        return self._client.generate_presigned_url("get_object", Params={"Bucket": self._bucket, "Key": storage_reference}, ExpiresIn=ttl)

    def delete(self, storage_reference: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=storage_reference)

    def read(self, storage_reference: str) -> bytes:
        buf = io.BytesIO()
        self._client.download_fileobj(self._bucket, storage_reference, buf)
        return buf.getvalue()


_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Point d'entrée unique — jamais instancier un backend directement
    ailleurs dans le code (Phase 5 §2.2 du plan de mission)."""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance
    if settings.STORAGE_BACKEND == "s3":
        _backend_instance = S3CompatibleStorageBackend(
            bucket=settings.STORAGE_S3_BUCKET, endpoint_url=settings.STORAGE_S3_ENDPOINT_URL,
            access_key=settings.STORAGE_S3_ACCESS_KEY, secret_key=settings.STORAGE_S3_SECRET_KEY, region=settings.STORAGE_S3_REGION,
        )
    else:
        _backend_instance = LocalFilesystemStorageBackend(root=settings.STORAGE_LOCAL_ROOT, signing_secret=settings.STORAGE_SIGNED_URL_SECRET)
    return _backend_instance
