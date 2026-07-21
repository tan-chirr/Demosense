"""Hand-computed rollup tests - matches the Phase 4 deliverable from the
plan: a county chair's aggregate row is provably equal to the sum of the
club rows beneath it. Uses db_session (rolled back after the test) since
services/rollup.py, like the other services, only flush()s.
"""

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from demosense.models.org import OrgLevel
from demosense.models.person import Person
from demosense.models.survey import Answer, Question, QuestionKind, RespondentKind, ResponseSet, Survey
from demosense.schemas.aggregate import AggregateRead
from demosense.services.hierarchy import create_org_unit
from demosense.services.rollup import MIN_RESPONDENTS_FOR_DETAIL, compute_stats, run_rollup_for_survey


@pytest_asyncio.fixture
async def rollup_world(db_session):
    """county -> {club_a, club_b}, a 2-question survey targeting the county,
    3 completed responses at club_a and 2 at club_b.
    """
    tag = uuid.uuid4().hex[:8]
    usa = await create_org_unit(db_session, level=OrgLevel.national, name="USA", slug=f"usa_{tag}")
    ca = await create_org_unit(db_session, level=OrgLevel.state, name="CA", slug=f"ca_{tag}", parent=usa)
    county = await create_org_unit(
        db_session, level=OrgLevel.county, name="Test County", slug=f"county_{tag}", parent=ca
    )
    club_a = await create_org_unit(
        db_session, level=OrgLevel.local, name="Club A", slug=f"club_a_{tag}", parent=county
    )
    club_b = await create_org_unit(
        db_session, level=OrgLevel.local, name="Club B", slug=f"club_b_{tag}", parent=county
    )

    survey = Survey(
        title=f"Rollup Test Survey {tag}",
        status="open",
        respondent=RespondentKind.person,
        target_org_unit_id=county.id,
    )
    db_session.add(survey)
    await db_session.flush()

    ordinal_q = Question(
        survey_id=survey.id, ordinal=1, kind=QuestionKind.ordinal, prompt="Rate 1-5",
        config={"min": 1, "max": 5},
    )
    choice_q = Question(
        survey_id=survey.id, ordinal=2, kind=QuestionKind.single_choice, prompt="Pick one",
        config={"options": ["a", "b", "c"]},
    )
    db_session.add_all([ordinal_q, choice_q])
    await db_session.flush()

    async def add_response(org_unit, ordinal_value, choice_value):
        person = Person(first_name="Test", last_name=f"Person{uuid.uuid4().hex[:6]}")
        db_session.add(person)
        await db_session.flush()

        response_set = ResponseSet(
            survey_id=survey.id,
            person_id=person.id,
            org_unit_id=org_unit.id,
            org_unit_path=org_unit.path,
            is_complete=True,
            submitted_at=datetime.now(timezone.utc),
        )
        db_session.add(response_set)
        await db_session.flush()

        db_session.add_all(
            [
                Answer(response_set_id=response_set.id, question_id=ordinal_q.id, value_numeric=ordinal_value),
                Answer(response_set_id=response_set.id, question_id=choice_q.id, value_choice=[choice_value]),
            ]
        )
        await db_session.flush()

    # club_a: ordinal [3, 4, 5], choices [a, a, b]
    await add_response(club_a, 3, "a")
    await add_response(club_a, 4, "a")
    await add_response(club_a, 5, "b")
    # club_b: ordinal [1, 2], choices [b, c]
    await add_response(club_b, 1, "b")
    await add_response(club_b, 2, "c")

    return {
        "survey": survey,
        "ordinal_q": ordinal_q,
        "choice_q": choice_q,
        "county": county,
        "club_a": club_a,
        "club_b": club_b,
    }


def _find(aggregates, *, org_unit_id, question_id):
    matches = [
        a for a in aggregates if a.org_unit_id == org_unit_id and a.question_id == question_id
    ]
    assert len(matches) == 1
    return matches[0]


async def test_club_level_ordinal_stats(db_session, rollup_world):
    aggregates = await run_rollup_for_survey(db_session, rollup_world["survey"])

    a = _find(aggregates, org_unit_id=rollup_world["club_a"].id, question_id=rollup_world["ordinal_q"].id)
    assert a.respondent_n == 3
    assert a.stats["sum"] == 12
    assert a.stats["mean"] == 4.0

    b = _find(aggregates, org_unit_id=rollup_world["club_b"].id, question_id=rollup_world["ordinal_q"].id)
    assert b.respondent_n == 2
    assert b.stats["sum"] == 3
    assert b.stats["mean"] == 1.5


async def test_county_ordinal_equals_sum_of_clubs(db_session, rollup_world):
    aggregates = await run_rollup_for_survey(db_session, rollup_world["survey"])

    county_agg = _find(
        aggregates, org_unit_id=rollup_world["county"].id, question_id=rollup_world["ordinal_q"].id
    )
    club_a_agg = _find(
        aggregates, org_unit_id=rollup_world["club_a"].id, question_id=rollup_world["ordinal_q"].id
    )
    club_b_agg = _find(
        aggregates, org_unit_id=rollup_world["club_b"].id, question_id=rollup_world["ordinal_q"].id
    )

    assert county_agg.respondent_n == club_a_agg.respondent_n + club_b_agg.respondent_n == 5
    assert county_agg.stats["sum"] == club_a_agg.stats["sum"] + club_b_agg.stats["sum"] == 15
    assert county_agg.stats["mean"] == 3.0  # 15/5, NOT the average of 4.0 and 1.5


async def test_county_choice_counts_equal_sum_of_clubs(db_session, rollup_world):
    aggregates = await run_rollup_for_survey(db_session, rollup_world["survey"])

    county_agg = _find(
        aggregates, org_unit_id=rollup_world["county"].id, question_id=rollup_world["choice_q"].id
    )
    assert county_agg.respondent_n == 5
    assert county_agg.stats["counts"] == {"a": 2, "b": 2, "c": 1}


async def test_rollup_is_idempotent_on_rerun(db_session, rollup_world):
    first = await run_rollup_for_survey(db_session, rollup_world["survey"])
    second = await run_rollup_for_survey(db_session, rollup_world["survey"])
    assert len(first) == len(second)
    # same underlying rows updated in place, not duplicated
    county_aggs = [
        a for a in second
        if a.org_unit_id == rollup_world["county"].id and a.question_id == rollup_world["ordinal_q"].id
    ]
    assert len(county_aggs) == 1


def test_compute_stats_text_question_returns_none():
    assert compute_stats(QuestionKind.text, []) is None


def test_confidentiality_threshold_suppresses_small_n():
    from demosense.models.aggregate import Aggregate

    small = Aggregate(
        survey_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        org_unit_id=uuid.uuid4(),
        respondent_n=MIN_RESPONDENTS_FOR_DETAIL - 1,
        stats={"n": MIN_RESPONDENTS_FOR_DETAIL - 1, "mean": 3.5},
        computed_at=datetime.now(timezone.utc),
    )
    read = AggregateRead.from_aggregate(small)
    assert read.suppressed is True
    assert read.stats is None
    assert read.respondent_n == MIN_RESPONDENTS_FOR_DETAIL - 1  # count itself still visible


def test_confidentiality_threshold_allows_large_n():
    from demosense.models.aggregate import Aggregate

    large = Aggregate(
        survey_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        org_unit_id=uuid.uuid4(),
        respondent_n=MIN_RESPONDENTS_FOR_DETAIL,
        stats={"n": MIN_RESPONDENTS_FOR_DETAIL, "mean": 3.5},
        computed_at=datetime.now(timezone.utc),
    )
    read = AggregateRead.from_aggregate(large)
    assert read.suppressed is False
    assert read.stats == {"n": MIN_RESPONDENTS_FOR_DETAIL, "mean": 3.5}
