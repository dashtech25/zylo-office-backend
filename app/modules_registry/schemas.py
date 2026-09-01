import uuid
from datetime import datetime

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


class InstalledModuleResponse(BaseModel):
    """Catalogue complet croisé avec le statut d'installation pour une
    organisation donnée — 'inactive' par défaut si le module n'a jamais été
    activé pour elle (aucune ligne OrganizationModule dans ce cas). Sert à
    la fois au tableau de bord (App Launcher, ne montrer que 'active') et à
    la marketplace de modules (montrer tout le catalogue avec son statut)."""

    moduleCode: str
    name: str
    description: str | None
    version: str
    status: str
    activatedAt: datetime | None
