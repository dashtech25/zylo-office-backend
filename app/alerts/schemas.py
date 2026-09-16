"""Schémas Pydantic du module Alertes — déplacés tels quels depuis
`app/modules/zylo_liquid/schemas.py` (2026-09-15, extraction Phase 3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ResolveAlertRequest(BaseModel):
    """D2 : réservé aux types sans vérification automatique possible
    (le service refuse la requête pour un type auto-vérifiable — voir
    `resolve_alert`). `resolutionNote` devient obligatoire à cet usage."""
    resolutionNote: str | None = Field(
        default=None,
        description="Justification de la résolution manuelle — obligatoire en pratique (le service renvoie 422 si absente), un simple champ optionnel côté schéma ne permettant pas de distinguer \"non fourni\" de \"chaîne vide\" avant validation métier.",
    )


class AlertResponse(BaseModel):
    id: uuid.UUID
    stationId: uuid.UUID | None = Field(default=None, description="Station à laquelle l'alerte est rattachée. Mutuellement exclusif de `truckId` en pratique (une alerte a une seule origine, station ou camion) même si la contrainte en base exige seulement qu'au moins l'un des deux soit renseigné.")
    truckId: uuid.UUID | None = Field(default=None, description="Camion auquel l'alerte est rattachée, en alternative à `stationId` (ex. type `truck_stop_unqualified` : arrêt hors de tout lieu connu).")
    vesselId: uuid.UUID | None = Field(default=None, description="Navire auquel l'alerte est rattachée, en alternative à `stationId`/`truckId` (ex. type `truck_stop_unqualified` pour un arrêt de navire hors de tout lieu connu).")
    tankId: uuid.UUID | None
    productId: uuid.UUID | None
    type: str = Field(description="Nature de l'alerte (ex. seuil de niveau, fuite suspectée, écart de réconciliation) — détermine si elle peut être vérifiée/résolue automatiquement.")
    severity: str = Field(description="Gravité calculée par le service à la création de l'alerte selon son `type` (\"critical\", \"high\", \"medium\" ou \"low\") — jamais dérivée côté client.")
    status: str = Field(description="Cycle de vie : déclenchée -> (optionnellement) acquittée via `/acknowledge` -> résolue (automatiquement, ou manuellement via `PATCH` pour les types qui le permettent).")
    sourceType: str | None = Field(description="Type de l'entité à l'origine du déclenchement (ex. mesure de cuve, résultat de réconciliation) — avec `sourceId`, permet de remonter à la donnée source de l'alerte.")
    sourceId: uuid.UUID | None = Field(description="Identifiant de l'entité à l'origine du déclenchement, à interpréter selon `sourceType` — référence logique, pas une clé étrangère stricte (peut ne plus exister).")
    triggeredAt: datetime
    triggeredValue: float | None = Field(description="Valeur mesurée ayant déclenché l'alerte, à comparer à `thresholdValue` — unité dépendante du `type` d'alerte.")
    thresholdValue: float | None
    acknowledgedAt: datetime | None
    acknowledgedByUserId: uuid.UUID | None
    resolvedAt: datetime | None
    resolvedByUserId: uuid.UUID | None
    resolutionMethod: str | None = Field(description="\"auto_verified\" si le contrôle sous-jacent est repassé sous le seuil de lui-même, \"manual_justified\" si résolue via `PATCH /alerts/{alert_id}` avec note obligatoire — jamais les deux en même temps.")
    resolutionNote: str | None = Field(description="Justification saisie lors d'une résolution manuelle (`resolutionMethod=\"manual_justified\"`) — toujours `null` pour une résolution automatique.")

    model_config = {"from_attributes": True}
