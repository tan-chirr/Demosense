"""Seed the two real DemoSense surveys (from DemoSense Surveys V1.pdf).
Idempotent - skips a survey if one with the same title already exists.

Deliberately excluded from Member Story: "AI Generated Summary" (source
question 9) - that's Phase 6 (AI summarization), explicitly last in the
plan, and belongs on the response as an assist feature once that phase
exists, not hardcoded into the schema now.

"Survey Date" (source question 1 of Hometown Survey) isn't a stored
question either - it's response_set.submitted_at, filled automatically.

Compound source questions (e.g. "how have jobs fared, guesstimate is
optional") are split into a primary question plus an optional numeric
follow-up, since our schema is one value per question.

Usage:
    python scripts/seed_surveys.py
"""

import asyncio

from sqlalchemy import select

from demosense.db import SessionLocal
from demosense.models.org import OrgLevel, OrgUnit
from demosense.models.survey import Question, QuestionKind, RespondentKind, Survey, SurveyStatus
from demosense.services.hierarchy import create_org_unit
from demosense.winloop import use_selector_event_loop_on_windows

COUNTRY_SLUG = "usa"
COUNTRY_NAME = "United States"

FIVE_POINT_CHANGE = ["Much worse", "Slightly worse", "No change", "Slightly better", "Much better"]

HOMETOWN_QUESTIONS = [
    dict(kind=QuestionKind.text, prompt="Town Name", is_required=True),
    dict(kind=QuestionKind.text, prompt="County", is_required=True),
    dict(kind=QuestionKind.text, prompt="State", is_required=True),
    dict(kind=QuestionKind.numeric, prompt="Town population", is_required=True, config={"min": 0}),
    dict(
        kind=QuestionKind.numeric,
        prompt="Town external population",
        help_text="How many people live nearby and frequent the town",
        config={"min": 0},
    ),
    dict(
        kind=QuestionKind.ordinal,
        prompt="Over the last year, how have economic conditions in your town changed?",
        is_required=True,
        config={"min": 1, "max": 5, "labels": FIVE_POINT_CHANGE},
    ),
    dict(
        kind=QuestionKind.ordinal,
        prompt="Over the last year, how have jobs fared?",
        is_required=True,
        config={
            "min": 1,
            "max": 5,
            "labels": [
                "Significant layoffs",
                "Some layoffs",
                "No change",
                "Some hiring",
                "Significant hiring",
            ],
        },
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Guesstimate of total jobs gained or lost",
        help_text="Optional",
    ),
    dict(
        kind=QuestionKind.ordinal,
        prompt="Over the last year, have businesses opened or closed?",
        is_required=True,
        config={
            "min": 1,
            "max": 3,
            "labels": ["One or more closures", "No change", "One or more new businesses"],
        },
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Guesstimate number of business closures/openings",
        help_text="Optional",
    ),
    dict(
        kind=QuestionKind.ordinal,
        prompt="Over the last year, how has the physical condition of the town changed?",
        is_required=True,
        config={"min": 1, "max": 5, "labels": FIVE_POINT_CHANGE},
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Estimated cost to fix downtown streets",
        config={"min": 0},
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Estimated cost to fix downtown buildings",
        config={"min": 0},
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Estimated cost to fix the water system",
        config={"min": 0},
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="Estimated cost to fix the sewer system",
        config={"min": 0},
    ),
    dict(
        kind=QuestionKind.numeric,
        prompt="What percentage of your town has high-speed internet?",
        is_required=True,
        config={"min": 0, "max": 100},
    ),
    dict(
        kind=QuestionKind.multi_choice,
        prompt="How is high-speed internet provided?",
        config={"options": ["satellite", "cable", "telephone", "other"]},
    ),
    dict(
        kind=QuestionKind.text,
        prompt="If 'other' was selected above, specify the provider type",
    ),
    dict(kind=QuestionKind.numeric, prompt="Number of family doctors available", config={"min": 0}),
    dict(kind=QuestionKind.numeric, prompt="Number of health clinics in your town", config={"min": 0}),
    dict(kind=QuestionKind.numeric, prompt="Number of dentists available", config={"min": 0}),
]

MEMBER_STORY_QUESTIONS = [
    dict(
        kind=QuestionKind.single_choice,
        prompt="Type of filing",
        is_required=True,
        help_text=(
            "Choose whether your name is attached to this story. If you file "
            "anonymously, the API call must also set anonymous=true - no name "
            "is ever stored for that submission."
        ),
        config={"options": ["anonymous", "recorded"]},
    ),
    dict(
        kind=QuestionKind.boolean,
        prompt="Can you be contacted about your post?",
        help_text="Not applicable if filed anonymously",
    ),
    dict(
        kind=QuestionKind.single_choice,
        prompt="Issue category",
        is_required=True,
        config={"options": ["economics", "healthcare", "infrastructure", "education", "housing"]},
    ),
    dict(kind=QuestionKind.text, prompt="Issue sub-category", help_text="Further breakdown"),
    dict(
        kind=QuestionKind.multi_choice,
        prompt="Keywords",
        help_text="Up to 5",
        config={"freeform": True, "max_items": 5},
    ),
    dict(
        kind=QuestionKind.text,
        prompt="Brief description",
        is_required=True,
        config={"max_length": 120},
    ),
    dict(kind=QuestionKind.text, prompt="Title", is_required=True, config={"max_length": 80}),
    dict(
        kind=QuestionKind.text,
        prompt="Description",
        is_required=True,
        help_text="Narrative description of the event(s)",
    ),
]


async def get_or_create_country(session) -> OrgUnit:
    existing = (await session.scalars(select(OrgUnit).filter_by(slug=COUNTRY_SLUG))).one_or_none()
    if existing is not None:
        return existing
    return await create_org_unit(session, level=OrgLevel.national, name=COUNTRY_NAME, slug=COUNTRY_SLUG)


async def seed_survey(session, *, title: str, description: str, questions: list[dict], target: OrgUnit) -> None:
    existing = (await session.scalars(select(Survey).filter_by(title=title))).one_or_none()
    if existing is not None:
        print(f"skipping {title!r} - already exists")
        return

    survey = Survey(
        title=title,
        description=description,
        status=SurveyStatus.open,
        respondent=RespondentKind.person,
        target_org_unit_id=target.id,
    )
    session.add(survey)
    await session.flush()

    for ordinal, q in enumerate(questions, start=1):
        session.add(
            Question(
                survey_id=survey.id,
                ordinal=ordinal,
                kind=q["kind"],
                prompt=q["prompt"],
                help_text=q.get("help_text"),
                is_required=q.get("is_required", False),
                config=q.get("config", {}),
            )
        )
    await session.flush()
    print(f"created {title!r} with {len(questions)} questions")


async def run() -> None:
    async with SessionLocal() as session:
        country = await get_or_create_country(session)
        await seed_survey(
            session,
            title="Hometown Survey",
            description=(
                "Record party member's impression of past and current economic "
                "and social conditions in the town."
            ),
            questions=HOMETOWN_QUESTIONS,
            target=country,
        )
        await seed_survey(
            session,
            title="Member Story",
            description="Ask Democratic Party members for stories that highlight social and economic issues.",
            questions=MEMBER_STORY_QUESTIONS,
            target=country,
        )
        await session.commit()


if __name__ == "__main__":
    use_selector_event_loop_on_windows()
    asyncio.run(run())
