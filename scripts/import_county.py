"""Import real club/member data from a flat CSV into the org hierarchy.

Expected CSV columns (header row required):
    state_name, county_name, club_name, first_name, last_name, email,
    phone, position_code

position_code must match a demosense.models.person.PositionType.code
(run scripts/seed_position_types.py first). Leave blank for an ordinary
member - it defaults to "member".

State/county/club org units are created on first sight and reused after
that (matched by a slug derived from the full ancestor chain, so a
"Washington" county in two different states doesn't collide). Re-running
this script against the same CSV is safe: existing org units, people
(matched by email), and active memberships are left alone.

Usage:
    python scripts/import_county.py path/to/county.csv
"""

import argparse
import asyncio
import csv
import re
import sys

from sqlalchemy import select

from demosense.db import SessionLocal
from demosense.models.org import OrgLevel, OrgUnit
from demosense.models.person import Membership, Person, PositionType
from demosense.services.hierarchy import create_org_unit
from demosense.winloop import use_selector_event_loop_on_windows

COUNTRY_SLUG = "usa"
COUNTRY_NAME = "United States"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return slug.strip("_")


async def get_or_create_org_unit(session, *, level, name, slug, parent):
    existing = (await session.scalars(select(OrgUnit).filter_by(slug=slug))).one_or_none()
    if existing is not None:
        return existing
    return await create_org_unit(session, level=level, name=name, slug=slug, parent=parent)


async def get_or_create_person(session, *, first_name, last_name, email, phone):
    if email:
        existing = (await session.scalars(select(Person).filter_by(email=email))).one_or_none()
        if existing is not None:
            return existing
    person = Person(first_name=first_name, last_name=last_name, email=email or None, phone=phone or None)
    session.add(person)
    await session.flush()
    return person


async def ensure_active_membership(session, *, person, org_unit, position_type):
    existing = (
        await session.scalars(
            select(Membership).filter_by(person_id=person.id, org_unit_id=org_unit.id, end_date=None)
        )
    ).one_or_none()
    if existing is not None:
        return existing
    membership = Membership(person=person, org_unit=org_unit, position_type=position_type)
    session.add(membership)
    await session.flush()
    return membership


async def run(csv_path: str) -> None:
    async with SessionLocal() as session:
        country = await get_or_create_org_unit(
            session, level=OrgLevel.national, name=COUNTRY_NAME, slug=COUNTRY_SLUG, parent=None
        )
        positions = {p.code: p for p in await session.scalars(select(PositionType))}
        if "member" not in positions:
            print("no position types found - run scripts/seed_position_types.py first", file=sys.stderr)
            sys.exit(1)

        rows_imported = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                state_name = row["state_name"].strip()
                county_name = row["county_name"].strip()
                club_name = row["club_name"].strip()

                state_slug = slugify(state_name)
                county_slug = f"{state_slug}_{slugify(county_name)}"
                club_slug = f"{county_slug}_{slugify(club_name)}"

                state = await get_or_create_org_unit(
                    session, level=OrgLevel.state, name=state_name, slug=state_slug, parent=country
                )
                county = await get_or_create_org_unit(
                    session, level=OrgLevel.county, name=county_name, slug=county_slug, parent=state
                )
                club = await get_or_create_org_unit(
                    session, level=OrgLevel.local, name=club_name, slug=club_slug, parent=county
                )

                position_code = row.get("position_code", "").strip() or "member"
                position = positions.get(position_code)
                if position is None:
                    print(f"unknown position_code {position_code!r}, defaulting to member", file=sys.stderr)
                    position = positions["member"]

                person = await get_or_create_person(
                    session,
                    first_name=row["first_name"].strip(),
                    last_name=row["last_name"].strip(),
                    email=row.get("email", "").strip(),
                    phone=row.get("phone", "").strip(),
                )
                await ensure_active_membership(session, person=person, org_unit=club, position_type=position)
                rows_imported += 1

        await session.commit()
        print(f"imported {rows_imported} rows from {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path")
    args = parser.parse_args()
    use_selector_event_loop_on_windows()
    asyncio.run(run(args.csv_path))
