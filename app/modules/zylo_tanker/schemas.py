"""Schémas Pydantic du module Zylo Tanker — CRUD minimal de `Vessel`, même
patron que `Truck` (`app/modules/zylo_liquid/schemas.py`)."""

import uuid

from pydantic import BaseModel, Field


class CreateVesselRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50, description="Immatriculation/code d'identification du navire — unique par organisation.")


class VesselResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    code: str

    model_config = {"from_attributes": True}
