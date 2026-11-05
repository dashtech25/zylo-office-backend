"""Schémas HTTP de l'export de données (BE-243).

Le périmètre est validé ici : `sujet` exige `sujetId`, `tenant` l'interdit. Les contrôles
qui dépendent de la base (appartenance du sujet, tenant courant) sont dans app/exports/service.py.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PerimetreExport(BaseModel):
    """Périmètre demandé : tout le tenant, ou un seul sujet.

    `tenantId` est optionnel ; s'il est fourni et diffère de l'organisation courante, la demande
    est refusée en 404 (CA-4) : un tenant ne peut pas demander l'export d'un autre."""

    type: Literal["tenant", "sujet"]
    sujetId: uuid.UUID | None = None
    tenantId: uuid.UUID | None = None

    @model_validator(mode="after")
    def _coherence(self) -> "PerimetreExport":
        if self.type == "sujet" and self.sujetId is None:
            raise ValueError("sujetId est requis pour un périmètre sujet.")
        if self.type == "tenant" and self.sujetId is not None:
            raise ValueError("sujetId n'est pas autorisé pour un périmètre tenant.")
        return self


class DemandeExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    perimetre: PerimetreExport


class ExportStatut(BaseModel):
    """Statut d'un job, sans contenu."""

    id: uuid.UUID
    statut: str
    perimetre: dict
    empreinte: str = Field(min_length=64, max_length=64)
    expireAt: datetime
    createdAt: datetime


class ExportTelechargement(BaseModel):
    """Contenu d'un export prêt, avec son empreinte SHA-256."""

    id: uuid.UUID
    empreinte: str
    contenu: list[dict]
