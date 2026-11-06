"""Schémas des moyens de paiement (BE-116).

La réponse ne porte jamais la valeur du token : seuls l'identifiant, l'état de sélection et la
date de création sont exposés (CA-2).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AjoutMoyenPaiementRequest(BaseModel):
    """Corps d'un ajout ou d'un remplacement : une référence de token, jamais une donnée de carte."""

    tokenReference: str = Field(min_length=1, max_length=255, description="Référence de token fournie par le prestataire de paiement.")


class MoyenPaiementResponse(BaseModel):
    """Méthode de paiement exposée au portail, sans valeur de token (CA-2)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    selected: bool
    createdAt: datetime
