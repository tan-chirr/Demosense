import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from demosense.db import Base


class OrgLevel(str, enum.Enum):
    national = "national"
    state = "state"
    region = "region"
    county = "county"
    local = "local"


class GroupKind(str, enum.Enum):
    caucus = "caucus"
    committee = "committee"
    issue_group = "issue_group"
    constituency_group = "constituency_group"


class OrgUnit(Base):
    __tablename__ = "org_unit"
    __table_args__ = (
        CheckConstraint(
            "(level = 'national') = (parent_id IS NULL)",
            name="national_has_no_parent",
        ),
        Index("ix_org_unit_parent_id", "parent_id"),
        Index("ix_org_unit_path", "path", postgresql_ops={"path": "text_pattern_ops"}),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="RESTRICT")
    )
    level: Mapped[OrgLevel] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Denormalised path (e.g. "usa.ca.santa_barbara.goleta_club"), maintained
    # by services/hierarchy.py on create and on reparent — see move_unit().
    path: Mapped[str] = mapped_column(Text, nullable=False)
    fips_code: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    parent: Mapped["OrgUnit | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["OrgUnit"]] = relationship(back_populates="parent")


class OrgGroup(Base):
    __tablename__ = "org_group"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[GroupKind] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    scope_org_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    scope_org_unit: Mapped["OrgUnit"] = relationship()
