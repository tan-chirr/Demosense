import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.org import OrgUnit
from demosense.models.person import Person
from demosense.schemas.org import OrgUnitCreate, OrgUnitRead
from demosense.schemas.person import PersonRead
from demosense.services.audit import log_action
from demosense.services.hierarchy import create_org_unit, get_active_members, get_subtree
from demosense.services.rbac import Scope, require_admin_access, require_read_scope

router = APIRouter(prefix="/org-units", tags=["org-units"])


@router.get("/{unit_id}", response_model=OrgUnitRead)
async def get_org_unit(
    unit_id: uuid.UUID,
    scope: Scope = Depends(require_read_scope),
    session: AsyncSession = Depends(get_session),
):
    if not scope.contains(unit_id):
        raise HTTPException(status_code=403, detail="not in your visible scope")
    unit = await session.get(OrgUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="org unit not found")
    return unit


@router.get("/{unit_id}/subtree", response_model=list[OrgUnitRead])
async def list_subtree(
    unit_id: uuid.UUID,
    scope: Scope = Depends(require_read_scope),
    session: AsyncSession = Depends(get_session),
):
    if not scope.contains(unit_id):
        raise HTTPException(status_code=403, detail="not in your visible scope")
    try:
        return await get_subtree(session, unit_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="org unit not found")


@router.get("/{unit_id}/members", response_model=list[PersonRead])
async def list_members(
    unit_id: uuid.UUID,
    include_descendants: bool = True,
    scope: Scope = Depends(require_read_scope),
    session: AsyncSession = Depends(get_session),
):
    if not scope.contains(unit_id):
        raise HTTPException(status_code=403, detail="not in your visible scope")
    try:
        return await get_active_members(session, unit_id, include_descendants=include_descendants)
    except ValueError:
        raise HTTPException(status_code=404, detail="org unit not found")


@router.post("", response_model=OrgUnitRead, status_code=201)
async def create_unit(
    payload: OrgUnitCreate,
    person: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    parent = None
    if payload.parent_id is None:
        if not person.is_superuser:
            raise HTTPException(
                status_code=403, detail="only a superuser may create a national-level org unit"
            )
    else:
        await require_admin_access(session, person, payload.parent_id)
        parent = await session.get(OrgUnit, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="parent org unit not found")

    try:
        unit = await create_org_unit(
            session,
            level=payload.level,
            name=payload.name,
            slug=payload.slug,
            parent=parent,
            fips_code=payload.fips_code,
            website_url=payload.website_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_action(
        session,
        actor_person_id=person.id,
        action="org_unit.create",
        entity_type="org_unit",
        entity_id=unit.id,
        detail={"name": unit.name, "slug": unit.slug, "level": unit.level.value},
    )
    await session.commit()
    return unit
