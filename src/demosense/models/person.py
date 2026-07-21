import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from demosense.db import Base


class Person(Base):
    __tablename__ = "person"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    phone: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    home_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id")
    )
    joined_party_on: Mapped[date | None] = mapped_column(Date)
    # is_active doubles as fastapi-users' account-enabled flag and "active
    # party member" - deliberate reuse, not every Person has a login (only
    # hashed_password IS NOT NULL rows do), so this is fine for v1: a
    # deactivated member also loses login access, which is the desired
    # behavior for someone who has left the party.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    # --- fastapi-users columns: only populated for people who have a login ---
    hashed_password: Mapped[str | None] = mapped_column(Text)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    home_org_unit: Mapped["OrgUnit | None"] = relationship()  # noqa: F821
    memberships: Mapped[list["Membership"]] = relationship(back_populates="person")
    role_grants: Mapped[list["RoleGrant"]] = relationship(  # noqa: F821
        back_populates="person", foreign_keys="RoleGrant.person_id"
    )


class PositionType(Base):
    __tablename__ = "position_type"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="100")


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        CheckConstraint(
            "(org_unit_id IS NOT NULL) <> (org_group_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="sane_dates"),
        Index(
            "one_active_club_membership",
            "person_id",
            "org_unit_id",
            unique=True,
            postgresql_where=text("end_date IS NULL AND org_unit_id IS NOT NULL"),
        ),
        Index(
            "one_active_group_membership",
            "person_id",
            "org_group_id",
            unique=True,
            postgresql_where=text("end_date IS NULL AND org_group_id IS NOT NULL"),
        ),
        Index("ix_membership_org_unit_active", "org_unit_id", postgresql_where=text("end_date IS NULL")),
        Index("ix_membership_org_group_active", "org_group_id", postgresql_where=text("end_date IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False
    )
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="CASCADE")
    )
    org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_group.id", ondelete="CASCADE")
    )
    position_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("position_type.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    person: Mapped["Person"] = relationship(back_populates="memberships")
    org_unit: Mapped["OrgUnit | None"] = relationship()  # noqa: F821
    org_group: Mapped["OrgGroup | None"] = relationship()  # noqa: F821
    position_type: Mapped["PositionType"] = relationship()
