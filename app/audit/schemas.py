import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class AuditLogResponse(BaseModel):
    """Entrée d'audit telle que lue par l'API (table `audit_event`, BE-007).

    `request_id` et `result` sont exposés pour la corrélation avec les journaux
    serveur et pour distinguer une action réussie d'une action refusée."""

    id: uuid.UUID
    actorUserId: uuid.UUID
    action: str
    entityType: str
    entityId: uuid.UUID | None
    scopeResourceType: str | None
    scopeResourceId: uuid.UUID | None
    summary: str
    changes: dict | None
    request_id: str
    result: str
    createdAt: datetime

    model_config = {"from_attributes": True}


class AuditEvenementResponse(BaseModel):
    """Événement d'audit tel que renvoyé par la consultation BE-172.

    Champs de la définition : acteur (`actorUserId`), cible (`entityType` /
    `entityId`), action, motif (`reason`), temps (`createdAt`), résultat
    (`result`), corrélation (`request_id`) et visibilité (`visibility`).
    `changes` ne contient jamais de secret : le service d'écriture le masque (BE-007)."""

    id: uuid.UUID
    actorUserId: uuid.UUID
    entityType: str
    entityId: uuid.UUID | None
    action: str
    reason: str | None
    summary: str
    changes: dict | None
    scopeResourceType: str | None
    scopeResourceId: uuid.UUID | None
    result: str
    request_id: str
    visibility: str | None
    createdAt: datetime

    model_config = {"from_attributes": True}


class ExportAuditCreate(BaseModel):
    """Demande d'export du journal d'audit (BE-173) : sujet, période bornée et motif obligatoire.

    `motif` est refusé s'il est vide ou fait uniquement d'espaces (CA-1, 422). La période
    doit être ordonnée : `dateFin` ne précède pas `dateDebut`."""

    sujet: str = Field(..., min_length=1, max_length=100, description="Valeur de `entityType` du sujet audité.")
    dateDebut: datetime = Field(..., description="Début de période, borne incluse.")
    dateFin: datetime = Field(..., description="Fin de période, borne incluse.")
    motif: str = Field(..., max_length=500, description="Motif de la demande, obligatoire.")

    @field_validator("sujet", "motif")
    @classmethod
    def _non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("ne peut pas être vide")
        return valeur.strip()

    @model_validator(mode="after")
    def _periode_ordonnee(self):
        if self.dateFin < self.dateDebut:
            raise ValueError("dateFin ne peut pas précéder dateDebut")
        return self


class ExportAuditResponse(BaseModel):
    """Job d'export tel que renvoyé par l'API. `lienTelechargement` est nul une fois expiré."""

    id: uuid.UUID
    sujet: str
    dateDebut: datetime
    dateFin: datetime
    motif: str
    statut: str
    creeAt: datetime
    expireAt: datetime
    lienTelechargement: str | None
