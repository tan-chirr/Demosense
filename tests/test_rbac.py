"""RBAC tests against the real API, over the real DB (Neon).

Unlike test_hierarchy.py, these hit HTTP endpoints whose route handlers
call session.commit() directly - there's no outer transaction to roll back.
Each test tears down exactly what it created (deepest org units first,
since org_unit.parent_id is ON DELETE RESTRICT) rather than relying on
rollback.
"""

import uuid

import pytest_asyncio
from sqlalchemy import delete

from demosense.db import SessionLocal
from demosense.models.org import OrgUnit
from demosense.models.person import Person


@pytest_asyncio.fixture
async def two_counties(client, superuser_token):
    """usa_rbactest -> ca_rbactest -> {county_a, county_b}, plus a
    county_admin registered and granted for each county.
    """
    tag = uuid.uuid4().hex[:8]  # unique per test run so slugs never collide
    headers = {"Authorization": f"Bearer {superuser_token}"}

    async def create_unit(level, name, slug, parent_id=None):
        resp = await client.post(
            "/org-units",
            headers=headers,
            json={"level": level, "name": name, "slug": slug, "parent_id": parent_id},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def register_and_grant(email, password, first, last, county_id):
        resp = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "first_name": first, "last_name": last},
        )
        assert resp.status_code == 201, resp.text
        person_id = resp.json()["id"]

        resp = await client.post(
            "/role-grants",
            headers=headers,
            json={"person_id": person_id, "role": "county_admin", "org_unit_id": county_id},
        )
        assert resp.status_code == 201, resp.text

        resp = await client.post(
            "/auth/jwt/login", data={"username": email, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return person_id, resp.json()["access_token"]

    usa = await create_unit("national", "USA (rbac test)", f"usa_rbactest_{tag}")
    ca = await create_unit("state", "CA (rbac test)", f"ca_rbactest_{tag}", usa["id"])
    county_a = await create_unit("county", "County A", f"county_a_rbactest_{tag}", ca["id"])
    county_b = await create_unit("county", "County B", f"county_b_rbactest_{tag}", ca["id"])

    person_a_id, token_a = await register_and_grant(
        f"admin_a_{tag}@democlub.dev", "PassA123!", "Alice", "AdminA", county_a["id"]
    )
    person_b_id, token_b = await register_and_grant(
        f"admin_b_{tag}@democlub.dev", "PassB123!", "Bob", "AdminB", county_b["id"]
    )

    yield {
        "usa_id": usa["id"],
        "ca_id": ca["id"],
        "county_a_id": county_a["id"],
        "county_b_id": county_b["id"],
        "token_a": token_a,
        "token_b": token_b,
        "person_a_id": person_a_id,
        "person_b_id": person_b_id,
    }

    async with SessionLocal() as session:
        await session.execute(delete(Person).where(Person.id.in_([person_a_id, person_b_id])))
        for unit_id in [county_a["id"], county_b["id"], ca["id"], usa["id"]]:
            await session.execute(delete(OrgUnit).where(OrgUnit.id == unit_id))
        await session.commit()


async def test_county_admin_reads_own_county(client, two_counties):
    resp = await client.get(
        f"/org-units/{two_counties['county_a_id']}",
        headers={"Authorization": f"Bearer {two_counties['token_a']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == two_counties["county_a_id"]


async def test_county_admin_blocked_from_other_county_read(client, two_counties):
    resp = await client.get(
        f"/org-units/{two_counties['county_b_id']}",
        headers={"Authorization": f"Bearer {two_counties['token_a']}"},
    )
    assert resp.status_code == 403


async def test_county_admin_blocked_from_other_county_members(client, two_counties):
    resp = await client.get(
        f"/org-units/{two_counties['county_b_id']}/members",
        headers={"Authorization": f"Bearer {two_counties['token_a']}"},
    )
    assert resp.status_code == 403


async def test_county_admin_can_create_club_in_own_county(client, two_counties):
    resp = await client.post(
        "/org-units",
        headers={"Authorization": f"Bearer {two_counties['token_a']}"},
        json={
            "level": "local",
            "name": "Test Club",
            "slug": f"club_{uuid.uuid4().hex[:8]}",
            "parent_id": two_counties["county_a_id"],
        },
    )
    assert resp.status_code == 201

    # cleanup - this club isn't tracked by the fixture's teardown list
    async with SessionLocal() as session:
        await session.execute(delete(OrgUnit).where(OrgUnit.id == resp.json()["id"]))
        await session.commit()


async def test_county_admin_blocked_from_creating_club_in_other_county(client, two_counties):
    resp = await client.post(
        "/org-units",
        headers={"Authorization": f"Bearer {two_counties['token_a']}"},
        json={
            "level": "local",
            "name": "Sneaky Club",
            "slug": f"sneaky_{uuid.uuid4().hex[:8]}",
            "parent_id": two_counties["county_b_id"],
        },
    )
    assert resp.status_code == 403


async def test_unauthenticated_request_is_rejected(client, two_counties):
    resp = await client.get(f"/org-units/{two_counties['county_a_id']}")
    assert resp.status_code == 401
