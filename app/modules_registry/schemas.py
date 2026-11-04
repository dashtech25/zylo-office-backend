import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ModuleResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    version: str

    model_config = {"from_attributes": True}


class OrganizationModuleResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    moduleCode: str
    status: str

    model_config = {"from_attributes": True}


class ActivateModuleRequest(BaseModel):
    moduleCode: str


class SetModuleActivationRequest(BaseModel):
    """Corps de `PUT /organizations/current/modules/{moduleId}/activation` (BE-022).

    `active` vrai active le module pour l'organisation courante, faux le désactive. Le module
    cible est porté par le chemin (son identifiant de catalogue), jamais par le corps."""

    active: bool


class InstalledModuleResponse(BaseModel):
    """Catalogue complet croisé avec le statut d'installation pour une
    organisation donnée — 'inactive' par défaut si le module n'a jamais été
    activé pour elle (aucune ligne OrganizationModule dans ce cas). Sert à
    la fois au tableau de bord (App Launcher, ne montrer que 'active') et à
    la marketplace de modules (montrer tout le catalogue avec son statut)."""

    moduleId: uuid.UUID
    moduleCode: str
    name: str
    description: str | None
    version: str
    status: str
    activatedAt: datetime | None
    accessState: Literal["not_configured", "active", "inactive", "expired", "blocked", "unknown"]
    canActivate: bool
    canOpen: bool


class ModuleAccessResponse(BaseModel):
    """Projection d'accès d'un module pour l'organisation courante (BE-025).

    `canActivate` dit si l'organisation peut activer le module (droit d'abonnement). `canOpen`
    dit si le module est en plus activé pour elle et que le registre le déclare disponible : c'est
    la seule valeur à consulter avant d'ouvrir le module. Les deux sont calculées côté serveur ;
    l'interface ne déduit jamais un droit de l'état brut."""

    moduleId: uuid.UUID
    moduleCode: str
    status: str
    accessState: Literal["not_configured", "active", "inactive", "expired", "blocked", "unknown"]
    canActivate: bool
    canOpen: bool


class ModuleAuditEventResponse(BaseModel):
    """Un événement de transition de module, tel que lu par `GET /organizations/{id}/module-audit` (BE-056).

    `moduleId` vient du scope de l'événement (nul si la transition n'en portait pas). La charge utile
    est celle, minimale, écrite à la publication : états et versions, jamais de secret.
    """

    id: uuid.UUID
    eventName: str
    subjectType: str | None
    subjectId: uuid.UUID | None
    moduleId: uuid.UUID | None
    actorId: uuid.UUID
    origin: str | None
    correlationId: str | None
    payloadMinimal: dict | None
    createdAt: datetime

    @classmethod
    def from_evenement(cls, evenement) -> "ModuleAuditEventResponse":
        return cls(
            id=evenement.id,
            eventName=evenement.eventName,
            subjectType=evenement.subjectType,
            subjectId=evenement.subjectId,
            moduleId=evenement.scopeResourceId,
            actorId=evenement.actorUserId,
            origin=evenement.origin,
            correlationId=evenement.correlationId,
            payloadMinimal=evenement.payloadMinimal,
            createdAt=evenement.createdAt,
        )
