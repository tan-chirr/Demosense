import uuid

from pydantic import BaseModel, ConfigDict

from demosense.models.org import OrgLevel


class OrgUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: OrgLevel
    name: str
    slug: str
    path: str
    fips_code: str | None
    website_url: str | None
    is_active: bool


class OrgUnitCreate(BaseModel):
    level: OrgLevel
    name: str
    slug: str
    parent_id: uuid.UUID | None = None
    fips_code: str | None = None
    website_url: str | None = None
