"""Schémas HTTP des demandes de support (BE-118).

Le corps ne porte que `contexte`. Tout autre champ (dont `createdBy`, CA-5, ou une pièce
jointe) est ignoré par Pydantic et n'atteint jamais la base.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DemandeSupportCreate(BaseModel):
    """Corps de `POST /organizations/{organization_id}/support-requests`.

    `contexte` est facultatif et doit être non secret : un mot de passe ou un token le fait
    refuser en 400 par le service (CA-2)."""

    contexte: dict[str, Any] | None = None


class DemandeSupportResponse(BaseModel):
    """Représentation d'une demande de support renvoyée par l'API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organizationId: uuid.UUID
    statut: str
    createdBy: uuid.UUID
    createdAt: datetime
