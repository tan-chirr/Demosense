import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.models.org import OrgUnit
from demosense.models.person import Membership, Person
from demosense.models.survey import Answer, Question, QuestionKind, ResponseSet, Survey

_EXPECTED_FIELD = {
    QuestionKind.boolean: "value_bool",
    QuestionKind.ordinal: "value_numeric",
    QuestionKind.numeric: "value_numeric",
    QuestionKind.single_choice: "value_choice",
    QuestionKind.multi_choice: "value_choice",
    QuestionKind.text: "value_text",
}


def validate_answer(
    question: Question,
    *,
    value_bool: bool | None = None,
    value_numeric: Decimal | None = None,
    value_text: str | None = None,
    value_choice: list[str] | None = None,
) -> None:
    """Raises ValueError if the given value doesn't fit question.kind/config.
    A missing (all-None) value is valid unless the question is required.
    """
    values = {
        "value_bool": value_bool,
        "value_numeric": value_numeric,
        "value_text": value_text,
        "value_choice": value_choice,
    }
    expected_field = _EXPECTED_FIELD[question.kind]

    other_fields_set = [f for f, v in values.items() if v is not None and f != expected_field]
    if other_fields_set:
        raise ValueError(
            f"question is kind={question.kind.value}; only {expected_field} may be set, "
            f"got {other_fields_set}"
        )

    if values[expected_field] is None:
        if question.is_required:
            raise ValueError(f"question {question.id} is required")
        return

    config = question.config or {}

    if question.kind in (QuestionKind.ordinal, QuestionKind.numeric):
        if "min" in config and value_numeric < config["min"]:
            raise ValueError(f"value {value_numeric} is below minimum {config['min']}")
        if "max" in config and value_numeric > config["max"]:
            raise ValueError(f"value {value_numeric} is above maximum {config['max']}")

    elif question.kind == QuestionKind.single_choice:
        if len(value_choice) != 1:
            raise ValueError("single_choice requires exactly one selected option")
        options = config.get("options")
        if options is not None and value_choice[0] not in options:
            raise ValueError(f"{value_choice[0]!r} is not a valid option")

    elif question.kind == QuestionKind.multi_choice:
        if config.get("freeform"):
            max_items = config.get("max_items")
            if max_items is not None and len(value_choice) > max_items:
                raise ValueError(f"at most {max_items} items allowed")
        else:
            options = config.get("options")
            if options is not None:
                invalid = set(value_choice) - set(options)
                if invalid:
                    raise ValueError(f"invalid options: {sorted(invalid)}")

    elif question.kind == QuestionKind.text:
        max_length = config.get("max_length")
        if max_length is not None and len(value_text) > max_length:
            raise ValueError(f"text exceeds max_length={max_length}")


async def create_response_set(
    session: AsyncSession,
    *,
    survey: Survey,
    org_unit: OrgUnit,
    person: Person | None,
    anonymous: bool = False,
) -> ResponseSet:
    target = await session.get(OrgUnit, survey.target_org_unit_id)
    if not (org_unit.path == target.path or org_unit.path.startswith(f"{target.path}.")):
        raise ValueError("org_unit is outside this survey's target scope")

    # Anonymous means anonymous: no person_id, and skip group_ids too since
    # caucus/committee membership can be identifying in a small group.
    group_ids: list[uuid.UUID] = []
    if person is not None and not anonymous:
        group_ids = list(
            await session.scalars(
                select(Membership.org_group_id).where(
                    Membership.person_id == person.id,
                    Membership.org_group_id.is_not(None),
                    Membership.end_date.is_(None),
                )
            )
        )

    response_set = ResponseSet(
        survey_id=survey.id,
        person_id=None if anonymous else (person.id if person else None),
        org_unit_id=org_unit.id,
        org_unit_path=org_unit.path,
        group_ids=group_ids,
    )
    session.add(response_set)
    await session.flush()
    return response_set


async def upsert_answers(
    session: AsyncSession, response_set: ResponseSet, answers_in: list
) -> list[Answer]:
    """answers_in: objects with question_id/value_bool/value_numeric/value_text/value_choice
    attributes (schemas.survey.AnswerIn). A fully-blank answer deletes any
    existing row for that question rather than storing an empty one.
    """
    if response_set.is_complete:
        raise ValueError("cannot edit a submitted response")

    questions = {
        q.id: q
        for q in await session.scalars(select(Question).where(Question.survey_id == response_set.survey_id))
    }

    results = []
    for answer_in in answers_in:
        question = questions.get(answer_in.question_id)
        if question is None:
            raise ValueError(f"question {answer_in.question_id} does not belong to this survey")

        validate_answer(
            question,
            value_bool=answer_in.value_bool,
            value_numeric=answer_in.value_numeric,
            value_text=answer_in.value_text,
            value_choice=answer_in.value_choice,
        )

        has_value = any(
            v is not None
            for v in (answer_in.value_bool, answer_in.value_numeric, answer_in.value_text, answer_in.value_choice)
        )
        existing = (
            await session.scalars(
                select(Answer).where(
                    Answer.response_set_id == response_set.id, Answer.question_id == question.id
                )
            )
        ).one_or_none()

        if not has_value:
            if existing is not None:
                await session.delete(existing)
            continue

        if existing is not None:
            existing.value_bool = answer_in.value_bool
            existing.value_numeric = answer_in.value_numeric
            existing.value_text = answer_in.value_text
            existing.value_choice = answer_in.value_choice
            results.append(existing)
        else:
            answer = Answer(
                response_set_id=response_set.id,
                question_id=question.id,
                value_bool=answer_in.value_bool,
                value_numeric=answer_in.value_numeric,
                value_text=answer_in.value_text,
                value_choice=answer_in.value_choice,
            )
            session.add(answer)
            results.append(answer)

    await session.flush()
    return results


async def submit_response_set(session: AsyncSession, response_set: ResponseSet) -> ResponseSet:
    if response_set.is_complete:
        raise ValueError("response already submitted")

    required_ids = set(
        await session.scalars(
            select(Question.id).where(
                Question.survey_id == response_set.survey_id, Question.is_required.is_(True)
            )
        )
    )
    answered_ids = set(
        await session.scalars(
            select(Answer.question_id).where(Answer.response_set_id == response_set.id)
        )
    )
    missing = required_ids - answered_ids
    if missing:
        raise ValueError(f"missing required questions: {sorted(str(m) for m in missing)}")

    response_set.is_complete = True
    response_set.submitted_at = datetime.now(timezone.utc)
    await session.flush()
    return response_set
