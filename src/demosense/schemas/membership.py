import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    org_unit_id: uuid.UUID | None
    org_group_id: uuid.UUID | None
    position_type_id: int
    start_date: date
    end_date: date | None
    notes: str | None


class MembershipCreate(BaseModel):
    person_id: uuid.UUID
    org_unit_id: uuid.UUID | None = None
    org_group_id: uuid.UUID | None = None
    position_code: str = "member"
    notes: str | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "MembershipCreate":
        if (self.org_unit_id is None) == (self.org_group_id is None):
            raise ValueError("exactly one of org_unit_id or org_group_id is required")
        return self
