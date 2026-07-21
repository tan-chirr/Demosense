import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from demosense.db import Base


class Aggregate(Base):
    """Precomputed rollup, one row per (survey, question, org node). Computed
    directly from answer+response_set filtered by org_unit_path prefix (or
    group_ids containment) - see services/rollup.py. Dashboards must read
    only this table, never `answer` - that's what makes them fast and is
    where the confidentiality threshold (respondent_n < 5) is enforced.
    """

    __tablename__ = "aggregate"
    __table_args__ = (
        UniqueConstraint("survey_id", "question_id", "org_unit_id", "org_group_id"),
        CheckConstraint(
            "(org_unit_id IS NOT NULL) <> (org_group_id IS NOT NULL)",
            name="exactly_one_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    survey_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("survey.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question.id", ondelete="CASCADE"), nullable=False
    )
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="CASCADE")
    )
    org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_group.id", ondelete="CASCADE")
    )
    respondent_n: Mapped[int] = mapped_column(Integer, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
