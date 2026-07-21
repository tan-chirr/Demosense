import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from demosense.models.survey import QuestionKind, RespondentKind, SurveyStatus


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    kind: QuestionKind
    prompt: str
    help_text: str | None
    is_required: bool
    config: dict


class SurveyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: SurveyStatus
    respondent: RespondentKind
    target_org_unit_id: uuid.UUID


class SurveyRead(SurveyListItem):
    questions: list[QuestionRead]


class ResponseSetCreate(BaseModel):
    org_unit_id: uuid.UUID
    # When true, person_id is never recorded for this response (even though
    # the API call itself is authenticated) - this is the actual anonymity
    # mechanism, not an inference from any particular answer's content.
    anonymous: bool = False


class ResponseSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    survey_id: uuid.UUID
    person_id: uuid.UUID | None
    org_unit_id: uuid.UUID
    org_unit_path: str
    group_ids: list[uuid.UUID]
    submitted_at: datetime | None
    is_complete: bool


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    value_bool: bool | None = None
    value_numeric: Decimal | None = None
    value_text: str | None = None
    value_choice: list[str] | None = None


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    value_bool: bool | None
    value_numeric: Decimal | None
    value_text: str | None
    value_choice: list[str] | None


class AnswersSubmitRequest(BaseModel):
    answers: list[AnswerIn]


class ResponseDetailRead(ResponseSetRead):
    answers: list[AnswerRead]
