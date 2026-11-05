"""Forme de la réponse HTTP d'une opération (BE-236).

`resultat` et `motifEchec` ne sont renseignés que dans leur état respectif : une
opération `inconnu` ne porte ni l'un ni l'autre, pour qu'un client ne puisse pas la lire
comme un succès ou un échec.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TransitionOperation(BaseModel):
    statut: str
    horodatage: datetime


class OperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    operationId: uuid.UUID
    type: str
    statut: str
    transitions: list[TransitionOperation]
    resultat: dict | None = None
    motifEchec: str | None = None
    derniereVerificationAt: datetime | None = None
