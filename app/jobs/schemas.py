"""Schémas HTTP des jobs d'import et d'export (BE-213)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.jobs.permissions import JOB_EXPORT_CLIENTS, JOB_IMPORT_CLIENTS


class CreateJobRequest(BaseModel):
    """Corps de `POST /api/v1/jobs`. La forme n'est pas fixée par la fiche (QE-API-01) :
    `idempotencyKey` rejoue la même demande sans créer de second job."""

    type: Literal[JOB_EXPORT_CLIENTS, JOB_IMPORT_CLIENTS]
    manifestSchemaVersion: int = Field(ge=1)
    idempotencyKey: str = Field(min_length=1, max_length=128)


class JobResponse(BaseModel):
    jobId: uuid.UUID
    type: str
    state: str
    manifestSchemaVersion: int
    expiresAt: datetime | None = None
    createdAt: datetime | None = None
