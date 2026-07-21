import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.models.aggregate import Aggregate
from demosense.models.survey import Answer, Question, QuestionKind, ResponseSet, Survey
from demosense.services.hierarchy import get_subtree

# Below this many respondents, the API redacts everything but the count -
# enforced at read time (services/rollup.py just computes and stores the
# full stats; api/routers/rollup.py applies the threshold on the way out).
MIN_RESPONDENTS_FOR_DETAIL = 5


def compute_stats(kind: QuestionKind, answers: list[Answer]) -> dict | None:
    """Pure function: raw completed answers -> a stats dict. Always includes
    "n" (respondent count) so callers have one consistent field to read.
    Returns None for text questions - free-text rollups are Phase 6 (AI
    summarization), not touched here.
    """
    if kind == QuestionKind.text:
        return None

    if kind == QuestionKind.boolean:
        values = [a.value_bool for a in answers if a.value_bool is not None]
        n = len(values)
        true_n = sum(1 for v in values if v)
        return {
            "n": n,
            "true_n": true_n,
            "false_n": n - true_n,
            "true_pct": (true_n / n * 100) if n else None,
        }

    if kind in (QuestionKind.ordinal, QuestionKind.numeric):
        values = [float(a.value_numeric) for a in answers if a.value_numeric is not None]
        n = len(values)
        if n == 0:
            return {"n": 0}
        distribution = Counter(values)
        return {
            "n": n,
            "sum": sum(values),
            "mean": sum(values) / n,
            "median": statistics.median(values),
            # storing sum+n (not just mean) is what lets a parent node's
            # aggregate be combined from children correctly later - you
            # cannot average averages of unequal-sized groups
            "distribution": {str(k): v for k, v in sorted(distribution.items())},
        }

    if kind in (QuestionKind.single_choice, QuestionKind.multi_choice):
        respondents = [a for a in answers if a.value_choice]
        counts: Counter = Counter()
        for a in respondents:
            counts.update(a.value_choice)
        return {"n": len(respondents), "counts": dict(counts)}

    raise ValueError(f"unhandled question kind: {kind}")


async def _upsert_aggregate(
    session: AsyncSession,
    *,
    survey_id: uuid.UUID,
    question_id: uuid.UUID,
    org_unit_id: uuid.UUID | None,
    org_group_id: uuid.UUID | None,
    stats: dict,
) -> Aggregate:
    conditions = [
        Aggregate.survey_id == survey_id,
        Aggregate.question_id == question_id,
        Aggregate.org_unit_id == org_unit_id if org_unit_id else Aggregate.org_unit_id.is_(None),
        Aggregate.org_group_id == org_group_id if org_group_id else Aggregate.org_group_id.is_(None),
    ]
    existing = (await session.scalars(select(Aggregate).where(*conditions))).one_or_none()
    if existing is not None:
        existing.respondent_n = stats["n"]
        existing.stats = stats
        existing.computed_at = datetime.now(timezone.utc)
        return existing

    aggregate = Aggregate(
        survey_id=survey_id,
        question_id=question_id,
        org_unit_id=org_unit_id,
        org_group_id=org_group_id,
        respondent_n=stats["n"],
        stats=stats,
    )
    session.add(aggregate)
    return aggregate


async def _answers_for_org_unit_path(session: AsyncSession, question_id: uuid.UUID, path: str) -> list[Answer]:
    stmt = (
        select(Answer)
        .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
        .where(
            Answer.question_id == question_id,
            ResponseSet.is_complete.is_(True),
            (ResponseSet.org_unit_path == path) | (ResponseSet.org_unit_path.like(f"{path}.%")),
        )
    )
    return list(await session.scalars(stmt))


async def _answers_for_org_group(session: AsyncSession, question_id: uuid.UUID, org_group_id: uuid.UUID) -> list[Answer]:
    stmt = (
        select(Answer)
        .join(ResponseSet, ResponseSet.id == Answer.response_set_id)
        .where(
            Answer.question_id == question_id,
            ResponseSet.is_complete.is_(True),
            ResponseSet.group_ids.contains([org_group_id]),
        )
    )
    return list(await session.scalars(stmt))


async def run_rollup_for_survey(session: AsyncSession, survey: Survey) -> list[Aggregate]:
    """Recompute every (question, org node) aggregate for a survey - both the
    org-unit tree (bottom-up by construction: each node's query naturally
    includes every descendant's completed answers) and, independently, any
    cross-cutting groups its respondents belong to.
    """
    questions = list(
        await session.scalars(select(Question).where(Question.survey_id == survey.id))
    )
    non_text_questions = [q for q in questions if q.kind != QuestionKind.text]

    org_units = await get_subtree(session, survey.target_org_unit_id, include_self=True)

    results: list[Aggregate] = []
    for org_unit in org_units:
        for question in non_text_questions:
            answers = await _answers_for_org_unit_path(session, question.id, org_unit.path)
            stats = compute_stats(question.kind, answers)
            results.append(
                await _upsert_aggregate(
                    session,
                    survey_id=survey.id,
                    question_id=question.id,
                    org_unit_id=org_unit.id,
                    org_group_id=None,
                    stats=stats,
                )
            )

    group_ids = list(
        await session.scalars(
            select(func.unnest(ResponseSet.group_ids))
            .where(ResponseSet.survey_id == survey.id, ResponseSet.is_complete.is_(True))
            .distinct()
        )
    )
    for group_id in group_ids:
        for question in non_text_questions:
            answers = await _answers_for_org_group(session, question.id, group_id)
            stats = compute_stats(question.kind, answers)
            results.append(
                await _upsert_aggregate(
                    session,
                    survey_id=survey.id,
                    question_id=question.id,
                    org_unit_id=None,
                    org_group_id=group_id,
                    stats=stats,
                )
            )

    await session.flush()
    return results
