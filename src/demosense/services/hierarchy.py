import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.models.org import OrgLevel, OrgUnit
from demosense.models.person import Membership, Person

# Canonical hierarchy order. A unit's level must sit strictly below its
# parent's level in this list — enforced in create_org_unit and move_unit
# so nobody accidentally makes a county the parent of a state.
LEVEL_ORDER = [OrgLevel.national, OrgLevel.state, OrgLevel.region, OrgLevel.county, OrgLevel.local]


def _build_path(parent: OrgUnit | None, slug: str) -> str:
    return slug if parent is None else f"{parent.path}.{slug}"


async def create_org_unit(
    session: AsyncSession,
    *,
    level: OrgLevel,
    name: str,
    slug: str,
    parent: OrgUnit | None = None,
    fips_code: str | None = None,
    website_url: str | None = None,
) -> OrgUnit:
    """Create an org unit with a correctly computed path.

    Always go through this (not a bare OrgUnit(...) + add) — path is
    denormalised and must be derived from the parent at creation time.
    """
    if (level == OrgLevel.national) != (parent is None):
        raise ValueError("national units have no parent; all others require one")
    if parent is not None and LEVEL_ORDER.index(level) <= LEVEL_ORDER.index(parent.level):
        raise ValueError(f"{level} cannot be a child of {parent.level}")

    unit = OrgUnit(
        parent_id=parent.id if parent else None,
        level=level,
        name=name,
        slug=slug,
        path=_build_path(parent, slug),
        fips_code=fips_code,
        website_url=website_url,
    )
    session.add(unit)
    await session.flush()
    return unit


async def get_subtree(
    session: AsyncSession, org_unit_id: uuid.UUID, *, include_self: bool = True
) -> list[OrgUnit]:
    """Every org unit at or below the given node, via the indexed path column."""
    root = await session.get(OrgUnit, org_unit_id)
    if root is None:
        raise ValueError(f"no org_unit with id {org_unit_id}")

    stmt = select(OrgUnit).where(OrgUnit.path.like(f"{root.path}.%"))
    result = await session.scalars(stmt)
    descendants = list(result)
    return [root, *descendants] if include_self else descendants


async def get_ancestors(session: AsyncSession, org_unit_id: uuid.UUID) -> list[OrgUnit]:
    """Chain from the root down to (but not including) the given node."""
    unit = await session.get(OrgUnit, org_unit_id)
    if unit is None:
        raise ValueError(f"no org_unit with id {org_unit_id}")

    ancestors: list[OrgUnit] = []
    current_id = unit.parent_id
    while current_id is not None:
        current = await session.get(OrgUnit, current_id)
        ancestors.append(current)
        current_id = current.parent_id
    ancestors.reverse()
    return ancestors


async def get_active_members(
    session: AsyncSession, org_unit_id: uuid.UUID, *, include_descendants: bool
) -> list[Person]:
    """Active club members (not group members) at a node, optionally including descendants."""
    if include_descendants:
        unit_ids = [u.id for u in await get_subtree(session, org_unit_id, include_self=True)]
    else:
        unit_ids = [org_unit_id]

    stmt = (
        select(Person)
        .join(Membership, Membership.person_id == Person.id)
        .where(
            Membership.org_unit_id.in_(unit_ids),
            Membership.end_date.is_(None),
            Person.is_active.is_(True),
        )
        .distinct()
        .order_by(Person.last_name, Person.first_name)
    )
    result = await session.scalars(stmt)
    return list(result)


async def move_unit(
    session: AsyncSession, unit_id: uuid.UUID, new_parent_id: uuid.UUID | None
) -> OrgUnit:
    """Reparent a unit, rewriting the path of the unit and every descendant."""
    unit = await session.get(OrgUnit, unit_id)
    if unit is None:
        raise ValueError(f"no org_unit with id {unit_id}")

    new_parent = await session.get(OrgUnit, new_parent_id) if new_parent_id else None
    if (unit.level == OrgLevel.national) != (new_parent is None):
        raise ValueError("national units have no parent; all others require one")
    if new_parent is not None and LEVEL_ORDER.index(unit.level) <= LEVEL_ORDER.index(new_parent.level):
        raise ValueError(f"{unit.level} cannot be a child of {new_parent.level}")

    subtree = await get_subtree(session, unit_id, include_self=True)
    if new_parent is not None and new_parent.id in {u.id for u in subtree}:
        raise ValueError("cannot reparent a unit under its own descendant")

    old_path = unit.path
    new_own_path = _build_path(new_parent, unit.slug)

    for descendant in subtree:
        descendant.path = new_own_path + descendant.path[len(old_path):]

    unit.parent_id = new_parent.id if new_parent else None
    await session.flush()
    return unit
