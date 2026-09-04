import uuid

from pydantic import BaseModel


class CreateOrganizationRequest(BaseModel):
    name: str
    slug: str


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}
