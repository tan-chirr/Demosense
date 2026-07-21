from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person, current_superuser
from demosense.db import get_session
from demosense.models.auth import AppRole, RoleGrant
from demosense.models.org import OrgGroup, OrgUnit
from demosense.models.person import Person
from demosense.schemas.role_grant import RoleGrantCreate, RoleGrantRead
from demosense.services.audit import log_action

# Granting a role is the most sensitive write in the system - restricted to
# superuser only for v1 rather than letting admins delegate sub-roles.
router = APIRouter(prefix="/role-grants", tags=["role-grants"])


@router.get("/me", response_model=list[RoleGrantRead])
async def get_my_role_grants(
    actor: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
):
    """A client's only way to discover "what org unit(s) can this logged-in
    user see" - there's no home_org_unit field on the user object itself,
    since a person's access comes from their role grants, not a single
    fixed home node. A superuser has none of these and should just treat
    that as "see everything" (is_superuser on /users/me already says so).
    """
    return list(
        await session.scalars(select(RoleGrant).where(RoleGrant.person_id == actor.id))
    )


@router.post("", response_model=RoleGrantRead, status_code=201, dependencies=[Depends(current_superuser)])
async def create_role_grant(
    payload: RoleGrantCreate,
    actor: Person = Depends(current_superuser),
    session: AsyncSession = Depends(get_session),
):
    target_person = await session.get(Person, payload.person_id)
    if target_person is None:
        raise HTTPException(status_code=404, detail="person not found")
    if payload.org_unit_id is not None and await session.get(OrgUnit, payload.org_unit_id) is None:
        raise HTTPException(status_code=404, detail="org unit not found")
    if payload.org_group_id is not None and await session.get(OrgGroup, payload.org_group_id) is None:
        raise HTTPException(status_code=404, detail="org group not found")

    if payload.role == AppRole.superuser:
        # keep the RoleGrant row and the fastapi-users login flag in sync -
        # rbac.py checks person.is_superuser directly, not this table.
        target_person.is_superuser = True

    grant = RoleGrant(
        person_id=payload.person_id,
        role=payload.role,
        org_unit_id=payload.org_unit_id,
        org_group_id=payload.org_group_id,
        granted_by=actor.id,
    )
    session.add(grant)
    await session.flush()

    await log_action(
        session,
        actor_person_id=actor.id,
        action="role_grant.create",
        entity_type="role_grant",
        entity_id=grant.id,
        detail={"person_id": str(payload.person_id), "role": payload.role.value},
    )
    await session.commit()
    return grant
