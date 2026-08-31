import uuid

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
