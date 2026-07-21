import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from demosense.db import Base


class AppRole(str, enum.Enum):
    member = "member"
    club_admin = "club_admin"
    county_admin = "county_admin"
    state_admin = "state_admin"
    national_admin = "national_admin"
    superuser = "superuser"


class RoleGrant(Base):
    __tablename__ = "role_grant"
    __table_args__ = (
        CheckConstraint(
            "role = 'superuser' OR (org_unit_id IS NOT NULL) <> (org_group_id IS NOT NULL)",
            name="scoped_grant_has_exactly_one_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[AppRole] = mapped_column(nullable=False)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="CASCADE")
    )
    org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_group.id", ondelete="CASCADE")
    )
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("person.id"))

    person: Mapped["Person"] = relationship(  # noqa: F821
        back_populates="role_grants", foreign_keys=[person_id]
    )
    org_unit: Mapped["OrgUnit | None"] = relationship(foreign_keys=[org_unit_id])  # noqa: F821
    org_group: Mapped["OrgGroup | None"] = relationship(foreign_keys=[org_group_id])  # noqa: F821
