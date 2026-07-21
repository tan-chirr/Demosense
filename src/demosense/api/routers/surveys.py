import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.org import OrgUnit
from demosense.models.person import Person
from demosense.models.survey import ResponseSet, Survey, SurveyStatus
from demosense.schemas.survey import (
    AnswerRead,
    AnswersSubmitRequest,
    ResponseDetailRead,
    ResponseSetCreate,
    ResponseSetRead,
    SurveyListItem,
    SurveyRead,
)
from demosense.services.audit import log_action
from demosense.services.rbac import has_admin_access
from demosense.services.survey import create_response_set, submit_response_set, upsert_answers

router = APIRouter(tags=["surveys"])


async def _require_response_access(session: AsyncSession, actor: Person, response_set: ResponseSet) -> None:
    """Owner of a named response, an admin covering its org unit, or a
    superuser may act on it. An anonymous response (person_id is None) has
    no owner to check against - any authenticated active person may act on
    it, since its unguessable id is the only way to reach it at all (no
    "list responses" endpoint exists in v1).
    """
    if response_set.person_id is None:
        return
    if actor.id == response_set.person_id or actor.is_superuser:
        return
    if await has_admin_access(session, actor, response_set.org_unit_id):
        return
    raise HTTPException(status_code=403, detail="not your response")


@router.get("/surveys", response_model=list[SurveyListItem])
async def list_surveys(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(Survey).where(Survey.status == SurveyStatus.open)))


@router.get("/surveys/{survey_id}", response_model=SurveyRead)
async def get_survey(survey_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise HTTPException(status_code=404, detail="survey not found")
    await session.refresh(survey, attribute_names=["questions"])
    return survey


@router.post("/surveys/{survey_id}/responses", response_model=ResponseSetRead, status_code=201)
async def start_response(
    survey_id: uuid.UUID,
    payload: ResponseSetCreate,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise HTTPException(status_code=404, detail="survey not found")
    if survey.status != SurveyStatus.open:
        raise HTTPException(status_code=400, detail="survey is not open")

    org_unit = await session.get(OrgUnit, payload.org_unit_id)
    if org_unit is None:
        raise HTTPException(status_code=404, detail="org unit not found")

    try:
        response_set = await create_response_set(
            session, survey=survey, org_unit=org_unit, person=actor, anonymous=payload.anonymous
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_action(
        session,
        actor_person_id=response_set.person_id,  # None if anonymous - see _require_response_access
        action="response_set.create",
        entity_type="response_set",
        entity_id=response_set.id,
        detail={"survey_id": str(survey_id), "org_unit_id": str(payload.org_unit_id)},
    )
    await session.commit()
    return response_set


@router.get("/responses/{response_set_id}", response_model=ResponseDetailRead)
async def get_response(
    response_set_id: uuid.UUID,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    response_set = await session.get(ResponseSet, response_set_id)
    if response_set is None:
        raise HTTPException(status_code=404, detail="response not found")
    await _require_response_access(session, actor, response_set)
    await session.refresh(response_set, attribute_names=["answers"])
    return response_set


@router.patch("/responses/{response_set_id}/answers", response_model=list[AnswerRead])
async def save_answers(
    response_set_id: uuid.UUID,
    payload: AnswersSubmitRequest,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    response_set = await session.get(ResponseSet, response_set_id)
    if response_set is None:
        raise HTTPException(status_code=404, detail="response not found")
    await _require_response_access(session, actor, response_set)

    try:
        answers = await upsert_answers(session, response_set, payload.answers)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_action(
        session,
        actor_person_id=response_set.person_id,
        action="response_set.save_answers",
        entity_type="response_set",
        entity_id=response_set.id,
        detail={"question_ids": [str(a.question_id) for a in payload.answers]},
    )
    await session.commit()
    return answers


@router.post("/responses/{response_set_id}/submit", response_model=ResponseSetRead)
async def submit_response(
    response_set_id: uuid.UUID,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    response_set = await session.get(ResponseSet, response_set_id)
    if response_set is None:
        raise HTTPException(status_code=404, detail="response not found")
    await _require_response_access(session, actor, response_set)

    try:
        await submit_response_set(session, response_set)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_action(
        session,
        actor_person_id=response_set.person_id,
        action="response_set.submit",
        entity_type="response_set",
        entity_id=response_set.id,
        detail={},
    )
    await session.commit()
    return response_set
