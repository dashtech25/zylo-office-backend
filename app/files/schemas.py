"""Schémas Pydantic du module Files — déplacés tels quels depuis
`app/modules/zylo_liquid/schemas.py` (2026-09-15, extraction Phase 1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CreateDocumentRequest(BaseModel):
    storageReference: str = Field(min_length=1, max_length=500, description="Référence opaque renvoyée par le service de stockage (app.shared.storage) après upload — jamais interprétée ici.")
    fileName: str = Field(min_length=1, max_length=255, description="Nom de fichier d'origine, affiché à l'utilisateur.")
    mimeType: str | None = None
    # Lien initial optionnel — un document peut aussi être créé sans lien et
    # rattaché ensuite via POST /document-links (association logique, Phase
    # 5 §6 : plusieurs entités peuvent référencer le même Document).
    linkedEntityType: str | None = Field(default=None, description="Type logique de l'entité liée (ex. 'PurchaseOrder') — texte libre, jamais une contrainte de clé étrangère : Files ne connaît aucune table d'un autre module.")
    linkedEntityId: uuid.UUID | None = None
    # Mission « vente-maintenant-reglementation », Phase 5 §4 — 'normal' par
    # défaut, 'restreint' nécessite DOCUMENT_READ_SENSITIVE pour être relu.
    sensitivityLevel: str = Field(default="normal", description="'normal' ou 'restreint' — 'restreint' exige la permission DOCUMENT_READ_SENSITIVE pour être relu ou téléchargé.")
    supersedesDocumentId: uuid.UUID | None = None

    @field_validator("sensitivityLevel")
    @classmethod
    def _validate_sensitivity_level(cls, value: str) -> str:
        if value not in ("normal", "restreint"):
            raise ValueError("sensitivityLevel doit être 'normal' ou 'restreint'.")
        return value


class DocumentResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    storageReference: str
    fileName: str
    mimeType: str | None
    uploadedByUserId: uuid.UUID
    sensitivityLevel: str
    supersedesDocumentId: uuid.UUID | None
    deletedAt: datetime | None

    model_config = {"from_attributes": True}


class CreateDocumentLinkRequest(BaseModel):
    documentId: uuid.UUID
    linkedEntityType: str = Field(min_length=1, max_length=40)
    linkedEntityId: uuid.UUID


class DocumentLinkResponse(BaseModel):
    id: uuid.UUID
    documentId: uuid.UUID
    linkedEntityType: str
    linkedEntityId: uuid.UUID

    model_config = {"from_attributes": True}


class DocumentDownloadUrlResponse(BaseModel):
    url: str = Field(description="Lien signé et temporaire vers le fichier — jamais un lien public permanent.")


class DocumentCountsResponse(BaseModel):
    """Nombre de pièces jointes par entité (audit performance — remplace
    un appel par ligne de tableau). Une entité absente des clés n'a
    simplement aucun document, jamais une erreur."""

    counts: dict[uuid.UUID, int]
