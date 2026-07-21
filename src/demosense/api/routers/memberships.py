import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.org import OrgGroup
from demosense.models.person import Membership, Person, PositionType
from demosense.schemas.membership import MembershipCreate, MembershipRead
from demosense.services.audit import log_action
from demosense.services.rbac import require_admin_access

router = APIRouter(prefix="/memberships", tags=["memberships"])


async def _admin_scope_unit_id(session: AsyncSession, payload: MembershipCreate) -> uuid.UUID:
    if payload.org_unit_id is not None:
        return payload.org_unit_id
    org_group = await session.get(OrgGroup, payload.org_group_id)
    if org_group is None:
        raise HTTPException(status_code=404, detail="org group not found")
    return org_group.scope_org_unit_id


@router.post("", response_model=MembershipRead, status_code=201)
async def create_membership(
    payload: MembershipCreate,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    scope_unit_id = await _admin_scope_unit_id(session, payload)
    await require_admin_access(session, actor, scope_unit_id)

    position = (
        await session.scalars(select(PositionType).where(PositionType.code == payload.position_code))
    ).one_or_none()
    if position is None:
        raise HTTPException(status_code=422, detail=f"unknown position_code {payload.position_code!r}")

    target_person = await session.get(Person, payload.person_id)
    if target_person is None:
        raise HTTPException(status_code=404, detail="person not found")

    membership = Membership(
        person_id=payload.person_id,
        org_unit_id=payload.org_unit_id,
        org_group_id=payload.org_group_id,
        position_type_id=position.id,
        notes=payload.notes,
    )
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail="an active membership already exists for this person and target"
        )

    await log_action(
        session,
        actor_person_id=actor.id,
        action="membership.create",
        entity_type="membership",
        entity_id=membership.id,
        detail={
            "person_id": str(payload.person_id),
            "org_unit_id": str(payload.org_unit_id) if payload.org_unit_id else None,
            "org_group_id": str(payload.org_group_id) if payload.org_group_id else None,
            "position_code": payload.position_code,
        },
    )
    await session.commit()
    return membership


@router.post("/{membership_id}/end", response_model=MembershipRead)
async def end_membership(
    membership_id: uuid.UUID,
    end_date: date | None = None,
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    membership = await session.get(Membership, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="membership not found")
    if membership.end_date is not None:
        raise HTTPException(status_code=400, detail="membership already ended")

    scope_unit_id = membership.org_unit_id
    if scope_unit_id is None:
        org_group = await session.get(OrgGroup, membership.org_group_id)
        scope_unit_id = org_group.scope_org_unit_id
    await require_admin_access(session, actor, scope_unit_id)

    membership.end_date = end_date or date.today()
    await log_action(
        session,
        actor_person_id=actor.id,
        action="membership.end",
        entity_type="membership",
        entity_id=membership.id,
        detail={"end_date": membership.end_date.isoformat()},
    )
    await session.commit()
    return membership
