import uuid
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.auth import current_active_person
from demosense.db import get_session
from demosense.models.auth import AppRole, RoleGrant
from demosense.models.person import Person
from demosense.services.hierarchy import get_subtree


@dataclass
class Scope:
    """Every org unit a person may read/write data for.

    `all` is true only for superusers - checked first so callers never have
    to materialise every org_unit id just to represent "everything".
    """

    all: bool = False
    org_unit_ids: set[uuid.UUID] = field(default_factory=set)

    def contains(self, org_unit_id: uuid.UUID) -> bool:
        return self.all or org_unit_id in self.org_unit_ids


async def visible_org_units(person: Person, session: AsyncSession) -> Scope:
    """Every org unit this person may read data for."""
    # person.is_superuser (the fastapi-users login flag) and an
    # AppRole.superuser RoleGrant row are kept in sync by role_grants.py -
    # check the flag directly so a superuser needs no grant row to have it.
    if person.is_superuser:
        return Scope(all=True)

    grants = list(
        await session.scalars(select(RoleGrant).where(RoleGrant.person_id == person.id))
    )

    scope = Scope()
    for grant in grants:
        if grant.role == AppRole.superuser:
            return Scope(all=True)
        if grant.org_unit_id is not None:
            subtree = await get_subtree(session, grant.org_unit_id, include_self=True)
            scope.org_unit_ids |= {u.id for u in subtree}
    return scope


async def require_read_scope(
    person: Person = Depends(current_active_person),
    session: AsyncSession = Depends(get_session),
) -> Scope:
    return await visible_org_units(person, session)


ADMIN_ROLES = {
    AppRole.club_admin,
    AppRole.county_admin,
    AppRole.state_admin,
    AppRole.national_admin,
}


async def has_admin_access(session: AsyncSession, person: Person, org_unit_id: uuid.UUID) -> bool:
    """True if person holds any admin-tier role (club_admin+) whose scope
    covers org_unit_id, or is superuser. Used to gate writes (creating org
    units, people, and memberships) - a plain 'member' role grant is
    read-only and does not satisfy this.
    """
    if person.is_superuser:
        return True

    grants = list(
        await session.scalars(select(RoleGrant).where(RoleGrant.person_id == person.id))
    )
    for grant in grants:
        if grant.role == AppRole.superuser:
            return True
        if grant.role in ADMIN_ROLES and grant.org_unit_id is not None:
            subtree = await get_subtree(session, grant.org_unit_id, include_self=True)
            if org_unit_id in {u.id for u in subtree}:
                return True
    return False


async def require_admin_access(session: AsyncSession, person: Person, org_unit_id: uuid.UUID) -> None:
    if not await has_admin_access(session, person, org_unit_id):
        raise HTTPException(status_code=403, detail="requires an admin role covering this org unit")
