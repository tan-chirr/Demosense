import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.aggregate import Aggregate
from demosense.models.person import Person
from demosense.models.survey import Survey
from demosense.schemas.aggregate import AggregateRead
from demosense.services.rbac import Scope, require_admin_access, require_read_scope
from demosense.services.rollup import run_rollup_for_survey

router = APIRouter(tags=["rollup"])


@router.post("/surveys/{survey_id}/rollup", response_model=list[AggregateRead])
async def trigger_rollup(
    survey_id: uuid.UUID,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise HTTPException(status_code=404, detail="survey not found")
    await require_admin_access(session, actor, survey.target_org_unit_id)

    aggregates = await run_rollup_for_survey(session, survey)
    await session.commit()
    return [AggregateRead.from_aggregate(a) for a in aggregates if a.org_unit_id is not None]


@router.get("/org-units/{unit_id}/aggregates", response_model=list[AggregateRead])
async def get_org_unit_aggregates(
    unit_id: uuid.UUID,
    survey_id: uuid.UUID,
    scope: Scope = Depends(require_read_scope),
    session: AsyncSession = Depends(get_session),
):
    if not scope.contains(unit_id):
        raise HTTPException(status_code=403, detail="not in your visible scope")

    aggregates = list(
        await session.scalars(
            select(Aggregate).where(Aggregate.survey_id == survey_id, Aggregate.org_unit_id == unit_id)
        )
    )
    return [AggregateRead.from_aggregate(a) for a in aggregates]
