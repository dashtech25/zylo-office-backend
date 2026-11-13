"""Schémas HTTP de la sortie de tenant (BE-246)."""

import uuid

from pydantic import BaseModel, Field


class DemandeSortie(BaseModel):
    """Corps de `POST /{organization_id}/exit`.

    `approbateurId` désigne la seconde personne qui approuve : elle doit être titulaire de
    `donnees.sortie.decider` et différente du demandeur (QE-EXP-15).
    """

    motif: str = Field(min_length=1, max_length=500)
    approbateurId: uuid.UUID


class SortieStatut(BaseModel):
    """Réponse de la demande : identifiant, état et attestation émise."""

    id: uuid.UUID
    etat: str
    attestation: dict
