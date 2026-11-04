import uuid
from datetime import datetime

from pydantic import BaseModel


class OperatorOrganizationItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}


class OperatorSubscriptionItem(BaseModel):
    id: uuid.UUID
    status: str
    planCode: str
    planName: str
    startDate: datetime
    endDate: datetime


class OperatorModuleItem(BaseModel):
    moduleCode: str
    name: str
    status: str


class OperatorOrganizationOverview(BaseModel):
    organization: OperatorOrganizationItem
    subscription: OperatorSubscriptionItem | None
    modules: list[OperatorModuleItem]


class OperatorHealthResponse(BaseModel):
    status: str
    database: str
    requestId: str | None


class OperatorTraceEvent(BaseModel):
    source: str
    action: str
    entityType: str
    createdAt: datetime


class OperatorRequestTrace(BaseModel):
    """Résultat de la recherche par request ID (BE-031 CA-4).

    `outcome` vaut `found` ou `not_found` (réponse 200). Un refus est un 403 et
    une erreur de lecture un 503 ; ces deux issues ne produisent pas ce corps.
    `found` est conservé pour les clients existants.
    """

    requestId: str
    found: bool
    outcome: str
    events: list[OperatorTraceEvent]


class OperatorPaymentEvent(BaseModel):
    provider: str
    eventId: str
    eventType: str
    requestId: str | None
    processedAt: datetime | None
    outcome: str
    createdAt: datetime

    model_config = {"from_attributes": True}


class ComposantSante(BaseModel):
    """Statut d'un composant technique, sans message d'erreur ni URL (BE-240).

    `status` vaut `ok`, `unavailable` ou `unknown`. Ces trois valeurs sont
    documentées dans `app/operator/health.py`.
    """

    name: str
    status: str


class StatutTechnique(BaseModel):
    """Réponse de la readiness interne et du statut opérateur (BE-240).

    `status` est `ready` seulement si tous les composants sont `ok`. `verifiedAt`
    est l'horodatage UTC de la vérification.
    """

    status: str
    verifiedAt: datetime
    components: list[ComposantSante]
