import uuid

from pydantic import BaseModel


class CityResponse(BaseModel):
    id: uuid.UUID
    name: str
    regionId: uuid.UUID
    regionName: str
    countryId: uuid.UUID
    countryName: str
    currencyCode: str

    model_config = {"from_attributes": True}
