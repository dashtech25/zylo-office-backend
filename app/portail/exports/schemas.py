"""Réponses HTTP des exports de données du portail (BE-117).

Aucun champ ne porte de mot de passe, de token ou de secret. `contenu` n'apparaît que dans la
réponse de téléchargement, et seulement pour un export prêt.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExportReponse(BaseModel):
    """Statut d'un export. `lienTelechargement` n'est renseigné qu'à l'état `ready` (CA-2)."""

    id: uuid.UUID
    statut: str
    perimetre: str
    expiresAt: datetime | None
    lienTelechargement: str | None
    createdAt: datetime


class ExportTelechargement(BaseModel):
    """Contenu d'un export prêt, renvoyé par le téléchargement journalisé."""

    id: uuid.UUID
    statut: str
    expiresAt: datetime | None
    contenu: list[dict[str, Any]]
