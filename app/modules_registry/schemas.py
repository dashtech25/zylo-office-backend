import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class CreerModuleRequest(BaseModel):
    """Corps de `POST /api/v1/admin/modules` (BE-042). `code` est la clé stable du catalogue."""

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)


class CreerVersionRequest(BaseModel):
    """Corps de `POST /api/v1/admin/modules/{moduleId}/versions` (BE-042). Crée une version en `draft`."""

    version: str = Field(min_length=1, max_length=50)
    digest: str | None = Field(default=None, max_length=200)
    provenance: str | None = Field(default=None, max_length=500)
    licence: str | None = Field(default=None, max_length=100)
    compatibility: dict | None = None
    prerequisites: list | None = None


class PublierVersionRequest(BaseModel):
    """Corps de `POST .../versions/{versionId}/publish` (BE-042).

    `stateVersion` est le compteur lu avant l'appel. `idempotencyKey` rend la commande rejouable :
    même clé, même résultat ; sans clé, aucun rejeu n'est reconnu."""

    stateVersion: int = Field(ge=1)
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=200)


class ModuleAdminResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    version: str
    publicationState: str
    visibility: str

    model_config = {"from_attributes": True}


class ModuleVersionAdminResponse(BaseModel):
    id: uuid.UUID
    moduleId: uuid.UUID
    version: str
    digest: str | None
    provenance: str | None
    licence: str | None
    compatibility: dict | None
    prerequisites: list | None
    stateVersion: int
    publicationState: str
    publishedAt: datetime | None

    model_config = {"from_attributes": True}
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


class CatalogueModuleResponse(BaseModel):
    """Ligne du catalogue public (BE-043) : seuls les champs sans valeur interne de publication."""

    code: str
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class UpgradePlanRequest(BaseModel):
    """Corps de `POST /api/v1/admin/modules/{moduleId}/upgrade-plans` (BE-044).

    Le plan est calculé entre deux versions existantes du module ; il n'est jamais exécuté."""

    fromVersion: str = Field(min_length=1, max_length=50)
    toVersion: str = Field(min_length=1, max_length=50)


class CompatibilityEvaluationResponse(BaseModel):
    """Résultat d'une évaluation de compatibilité (BE-044) : `result` et les `reasons` (motifs)."""

    id: uuid.UUID
    moduleVersionId: uuid.UUID
    result: str
    reasons: list
    evaluatedAt: datetime

    model_config = {"from_attributes": True}


class UpgradePlanResponse(BaseModel):
    """Plan de mise à jour entre deux versions (BE-044). `forwardOnly` vaut vrai sans retour arrière possible."""

    id: uuid.UUID
    moduleId: uuid.UUID
    fromVersion: str
    toVersion: str
    steps: list
    rollbackPossible: bool
    forwardOnly: bool

    model_config = {"from_attributes": True}


class VersionPublieeCatalogue(BaseModel):
    """Version publiée exposée dans une fiche publique (BE-043). Aucune version non publiée."""

    version: str
    publishedAt: datetime | None


class FicheModuleCatalogue(BaseModel):
    """Fiche publique d'un module (BE-043) : identité et versions publiées uniquement."""

    code: str
    name: str
    description: str | None
    versions: list[VersionPublieeCatalogue]


class ModulePermissionResponse(BaseModel):
    """Permission déclarée par la version installée d'un module (BE-055)."""

    id: uuid.UUID
    code: str
    description: str | None
    scope: Literal["organization", "tenant", "platform"]

    model_config = {"from_attributes": True}


class InstallModuleRequest(BaseModel):
    """Corps de `POST /organizations/{orgId}/modules/{moduleId}/installations` (BE-047).

    `stateVersion` : version d'état attendue ; 0 pour une organisation sans installation en cours."""

    moduleVersionId: uuid.UUID
    stateVersion: int = Field(ge=0)


class UpgradeModuleRequest(BaseModel):
    """Corps de `POST /organizations/{orgId}/modules/{moduleId}/upgrades` (BE-051).

    `stateVersion` : version d'état lue sur l'installation. `confirmationForwardOnly` : confirmation
    explicite exigée quand le plan BE-044 n'a pas de retour arrière prouvé (faux par défaut)."""

    targetModuleVersionId: uuid.UUID
    stateVersion: int = Field(ge=0)
    confirmationForwardOnly: bool = False


class ModuleInstallationResponse(BaseModel):
    """Installation technique renvoyée par les routes BE-047 (état courant et identifiant d'opération)."""

    id: uuid.UUID
    organizationId: uuid.UUID
    moduleId: uuid.UUID
    moduleVersionId: uuid.UUID
    state: str
    stateVersion: int
    operationId: uuid.UUID
    lastErrorCode: str | None
    upgradeTargetVersionId: uuid.UUID | None = None
    upgradeState: str | None = None

    model_config = {"from_attributes": True}


class DisponibiliteRequest(BaseModel):
    """Corps des routes d'activation et de désactivation de disponibilité (BE-048).

    `stateVersion` est la version d'état lue par le client ; `confirm` doit valoir `true` (garde de
    confirmation explicite)."""

    stateVersion: int = Field(ge=0)
    confirm: bool = False


class DisponibiliteResponse(BaseModel):
    """Disponibilité d'un module pour l'organisation : état courant et explication (BE-048)."""

    id: uuid.UUID
    organizationId: uuid.UUID
    moduleId: uuid.UUID
    moduleVersionId: uuid.UUID
    state: str
    stateVersion: int
    operationId: uuid.UUID
    lastErrorCode: str | None
    explanation: str
