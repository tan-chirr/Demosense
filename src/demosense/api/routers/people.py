import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.person import Membership, Person
from demosense.schemas.person import PersonCreate, PersonRead
from demosense.services.audit import log_action
from demosense.services.rbac import require_admin_access, visible_org_units

router = APIRouter(prefix="/people", tags=["people"])


@router.get("/{person_id}", response_model=PersonRead)
async def get_person(
    person_id: uuid.UUID,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    person = await session.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")

    if actor.id != person.id and not actor.is_superuser:
        scope = await visible_org_units(actor, session)
        memberships = list(
            await session.scalars(
                select(Membership).where(
                    Membership.person_id == person.id, Membership.end_date.is_(None)
                )
            )
        )
        if not any(m.org_unit_id and scope.contains(m.org_unit_id) for m in memberships):
            raise HTTPException(status_code=403, detail="not in your visible scope")

    return person


@router.post("", response_model=PersonRead, status_code=201)
async def create_person(
    payload: PersonCreate,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    if payload.home_org_unit_id is not None:
        await require_admin_access(session, actor, payload.home_org_unit_id)
    elif not actor.is_superuser:
        raise HTTPException(
            status_code=403, detail="home_org_unit_id is required unless you are a superuser"
        )

    person = Person(**payload.model_dump())
    session.add(person)
    await session.flush()

    await log_action(
        session,
        actor_person_id=actor.id,
        action="person.create",
        entity_type="person",
        entity_id=person.id,
        detail={"first_name": person.first_name, "last_name": person.last_name},
    )
    await session.commit()
    return person
