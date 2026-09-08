import uuid

from pydantic import BaseModel, Field


class CreateOrganizationRequest(BaseModel):
    name: str
    slug: str


class UpdateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}
