"""Schémas Pydantic du module Zylo Tanker — CRUD minimal de `Vessel`, même
patron que `Truck` (`app/modules/zylo_liquid/schemas.py`)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateVesselRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50, description="Immatriculation/code d'identification du navire — unique par organisation.")


class VesselResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    code: str
    destinationLatitude: float | None = Field(default=None, description="null si aucune destination n'est actuellement fixée.")
    destinationLongitude: float | None = Field(default=None, description="null si aucune destination n'est actuellement fixée.")
    destinationLabel: str | None = Field(default=None, description="Libellé libre de la destination — optionnel même quand une destination est fixée.")
    destinationSetAt: datetime | None = Field(default=None, description="null si aucune destination n'est actuellement fixée.")

    model_config = {"from_attributes": True}


class SetVesselDestinationRequest(BaseModel):
    """Fixe (ou remplace) la destination d'un navire — les trois champs de
    destination sont toujours renseignés ensemble côté modèle
    (`set_vessel_destination` horodate `destinationSetAt` lui-même, jamais
    fourni par le client)."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=150)
