import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from demosense.models.auth import AppRole


class RoleGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    role: AppRole
    org_unit_id: uuid.UUID | None
    org_group_id: uuid.UUID | None
    granted_at: datetime
    granted_by: uuid.UUID | None


class RoleGrantCreate(BaseModel):
    person_id: uuid.UUID
    role: AppRole
    org_unit_id: uuid.UUID | None = None
    org_group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def target_matches_role(self) -> "RoleGrantCreate":
        if self.role == AppRole.superuser:
            if self.org_unit_id is not None or self.org_group_id is not None:
                raise ValueError("superuser grants must not specify a scope")
        elif (self.org_unit_id is None) == (self.org_group_id is None):
            raise ValueError("exactly one of org_unit_id or org_group_id is required")
        return self
