"""Schémas Pydantic du module Alertes — déplacés tels quels depuis
`app/modules/zylo_liquid/schemas.py` (2026-09-15, extraction Phase 3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ResolveAlertRequest(BaseModel):
    """D2 : réservé aux types sans vérification automatique possible
    (le service refuse la requête pour un type auto-vérifiable — voir
    `resolve_alert`). `resolutionNote` devient obligatoire à cet usage."""
    resolutionNote: str | None = None


class AlertResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID | None = None
    truckId: uuid.UUID | None = None
    tankId: uuid.UUID | None
    productId: uuid.UUID | None
    type: str = Field(description="Nature de l'alerte (ex. seuil de niveau, fuite suspectée, écart de réconciliation) — détermine si elle peut être vérifiée/résolue automatiquement.")
    severity: str
    status: str = Field(description="Cycle de vie : déclenchée -> (optionnellement) acquittée via `/acknowledge` -> résolue (automatiquement, ou manuellement via `PATCH` pour les types qui le permettent).")
    sourceType: str | None = Field(description="Type de l'entité à l'origine du déclenchement (ex. mesure de cuve, résultat de réconciliation) — avec `sourceId`, permet de remonter à la donnée source de l'alerte.")
    sourceId: uuid.UUID | None
    triggeredAt: datetime
    triggeredValue: float | None = Field(description="Valeur mesurée ayant déclenché l'alerte, à comparer à `thresholdValue` — unité dépendante du `type` d'alerte.")
    thresholdValue: float | None
    acknowledgedAt: datetime | None
    acknowledgedByUserId: uuid.UUID | None
    resolvedAt: datetime | None
    resolvedByUserId: uuid.UUID | None
    resolutionMethod: str | None = Field(description="\"auto_verified\" si le contrôle sous-jacent est repassé sous le seuil de lui-même, \"manual_justified\" si résolue via `PATCH /alerts/{alert_id}` avec note obligatoire — jamais les deux en même temps.")
    resolutionNote: str | None

    model_config = {"from_attributes": True}
