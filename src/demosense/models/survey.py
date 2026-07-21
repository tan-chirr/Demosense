import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, SmallInteger, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from demosense.db import Base


class QuestionKind(str, enum.Enum):
    boolean = "boolean"
    ordinal = "ordinal"
    single_choice = "single_choice"
    multi_choice = "multi_choice"
    numeric = "numeric"
    text = "text"


class SurveyStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    closed = "closed"
    archived = "archived"


class RespondentKind(str, enum.Enum):
    person = "person"
    club = "club"


class Survey(Base):
    __tablename__ = "survey"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SurveyStatus] = mapped_column(nullable=False, server_default=SurveyStatus.draft.value)
    respondent: Mapped[RespondentKind] = mapped_column(
        nullable=False, server_default=RespondentKind.person.value
    )
    # who is allowed/asked to respond: everyone at or below this node
    target_org_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id"), nullable=False
    )
    target_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("org_group.id"))
    opens_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    is_recurring: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    recurrence_rule: Mapped[str | None] = mapped_column(Text)  # iCal RRULE
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("person.id"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="survey", order_by="Question.ordinal"
    )


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (UniqueConstraint("survey_id", "ordinal"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    survey_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("survey.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[QuestionKind] = mapped_column(nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # kind-specific config, e.g. {"min":1,"max":5,"labels":[...]} or
    # {"options":[...]} or {"max_length":120} or {"freeform":true,"max_items":5}
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    survey: Mapped["Survey"] = relationship(back_populates="questions")


class ResponseSet(Base):
    """One filing of a survey. Deliberately NOT unique per (survey, person) -
    both surveys this schema was built for (Hometown Survey, Member Story)
    are repeatable over time (conditions change, members submit more than
    one story), unlike a fixed-window monthly report. A single-submission
    survey is a UI convention, not a DB constraint, in this schema.
    """

    __tablename__ = "response_set"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    survey_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("survey.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id", ondelete="SET NULL")
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("org_unit.id"), nullable=False)
    # frozen copy of org_unit.path at submission time - a response filed by
    # Goleta in March stays attributed to Goleta even if reorganized later
    org_unit_path: Mapped[str] = mapped_column(Text, nullable=False)
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    is_complete: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    __table_args__ = (Index("ix_response_set_survey_path", "survey_id", "org_unit_path"),)

    answers: Mapped[list["Answer"]] = relationship(back_populates="response_set", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answer"
    __table_args__ = (UniqueConstraint("response_set_id", "question_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    response_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("response_set.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question.id", ondelete="CASCADE"), nullable=False
    )
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_choice: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    response_set: Mapped["ResponseSet"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship()
