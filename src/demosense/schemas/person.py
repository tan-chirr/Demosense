import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr | None
    phone: str | None
    postal_code: str | None
    home_org_unit_id: uuid.UUID | None
    joined_party_on: date | None
    is_active: bool


class PersonCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr | None = None
    phone: str | None = None
    postal_code: str | None = None
    home_org_unit_id: uuid.UUID | None = None
    joined_party_on: date | None = None
