"""Schémas HTTP du module support (BE-262)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AccesSupportCreate(BaseModel):
    """Corps de `POST /organizations/{organization_id}/acces-support`.

    `mode` vaut `lecture` si absent (CA-1). `justification` est obligatoire
    (CA-3). `finUtc` absent : fin à 24 h (durée NON DÉFINI, QE-FON-05)."""

    supportUserId: uuid.UUID
    justification: str
    mode: str = "lecture"
    finUtc: datetime | None = None


class AccesSupportResponse(BaseModel):
    """Représentation d'un accès support renvoyée par l'API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organizationId: uuid.UUID
    supportUserId: uuid.UUID
    creeParUserId: uuid.UUID
    mode: str
    justification: str
    debutUtc: datetime
    finUtc: datetime
    approbationId: uuid.UUID | None
