"""Schémas HTTP de la vérification d'organisation (BE-103).

La réponse ne porte jamais `motifInterne` (CA-3) : le champ n'existe pas dans le schéma de sortie.
Le corps du dépôt n'a aucun champ : tout champ envoyé, dont `statut`, est refusé en 422 (CA-4).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DepotVerificationRequest(BaseModel):
    """Corps de `POST /organizations/{organization_id}/verification` : vide, aucun champ accepté."""

    model_config = ConfigDict(extra="forbid")


class VerificationCaseResponse(BaseModel):
    """Représentation d'un cas de vérification renvoyée par l'API, sans motif interne."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organizationId: uuid.UUID
    statut: str
    createdAt: datetime
    updatedAt: datetime
