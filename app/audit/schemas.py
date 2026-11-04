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
