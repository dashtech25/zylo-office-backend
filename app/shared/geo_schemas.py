import uuid

from pydantic import BaseModel


class CityResponse(BaseModel):
    id: uuid.UUID
    name: str
    regionId: uuid.UUID
    regionName: str
    countryId: uuid.UUID
    countryName: str
    currencyId: uuid.UUID | None
    currencyCode: str

    model_config = {"from_attributes": True}


class CountryResponse(BaseModel):
    id: uuid.UUID
    name: str
    isoCode2: str
    currencyId: uuid.UUID | None
    currencyCode: str
    defaultTimezone: str

    model_config = {"from_attributes": True}
