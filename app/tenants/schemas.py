"""Schémas d'entrée et de sortie des routes `/api/v1/tenants` (BE-185).

Les champs JSON sont en camelCase, comme le reste de l'API. `expectedVersion`
porte le verrou de version : la requête n'est acceptée que si elle vise la
version courante du tenant.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreerTenantRequest(BaseModel):
    """Corps de `POST /api/v1/tenants` : le slug, identifiant lisible et unique."""

    slug: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


class TransitionTenantRequest(BaseModel):
    """Corps de `POST /api/v1/tenants/{tenant_id}/transitions`."""

    targetState: str = Field(min_length=1, max_length=20)
    expectedVersion: int = Field(ge=1)


class TenantResponse(BaseModel):
    """Représentation d'un tenant renvoyée par l'API."""

    model_config = ConfigDict(from_attributes=True)

    tenantId: uuid.UUID
    slug: str
    state: str
    version: int
    createdAt: datetime
    closedAt: datetime | None
