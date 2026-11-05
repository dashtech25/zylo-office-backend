import uuid
from datetime import datetime

from pydantic import BaseModel


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
