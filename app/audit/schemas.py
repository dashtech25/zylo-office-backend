import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actorUserId: uuid.UUID
    action: str
    entityType: str
    entityId: uuid.UUID | None
    scopeResourceType: str | None
    scopeResourceId: uuid.UUID | None
    summary: str
    changes: dict | None
    createdAt: datetime

    model_config = {"from_attributes": True}
