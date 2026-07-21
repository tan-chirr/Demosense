import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from demosense.models.org import OrgLevel
from demosense.models.person import Membership, Person
from demosense.services.hierarchy import (
    create_org_unit,
    get_active_members,
    get_ancestors,
    get_subtree,
    move_unit,
)


@pytest_asyncio.fixture
async def sample_tree(db_session):
    """{usa} -> {ca} -> {santa_barbara -> {goleta, montecito}, ventura}

    Slugs are tagged unique-per-test-run - org_unit.slug is globally unique,
    and real seed data (scripts/seed_surveys.py, scripts/import_county.py)
    commits a real "usa" national unit outside this test's transaction, so a
    bare "usa" slug here would collide with it.
    """
    tag = uuid.uuid4().hex[:8]
    usa = await create_org_unit(db_session, level=OrgLevel.national, name="USA", slug=f"usa_{tag}")
    ca = await create_org_unit(
        db_session, level=OrgLevel.state, name="California", slug=f"ca_{tag}", parent=usa
    )
    santa_barbara = await create_org_unit(
        db_session, level=OrgLevel.county, name="Santa Barbara", slug=f"santa_barbara_{tag}", parent=ca
    )
    ventura = await create_org_unit(
        db_session, level=OrgLevel.county, name="Ventura", slug=f"ventura_{tag}", parent=ca
    )
    goleta = await create_org_unit(
        db_session, level=OrgLevel.local, name="Goleta Club", slug=f"goleta_{tag}", parent=santa_barbara
    )
    montecito = await create_org_unit(
        db_session, level=OrgLevel.local, name="Montecito Club", slug=f"montecito_{tag}", parent=santa_barbara
    )
    return {
        "tag": tag,
        "usa": usa,
        "ca": ca,
        "santa_barbara": santa_barbara,
        "ventura": ventura,
        "goleta": goleta,
        "montecito": montecito,
    }


async def test_paths_are_dotted_from_root(sample_tree):
    tag = sample_tree["tag"]
    assert sample_tree["usa"].path == f"usa_{tag}"
    assert sample_tree["ca"].path == f"usa_{tag}.ca_{tag}"
    assert sample_tree["santa_barbara"].path == f"usa_{tag}.ca_{tag}.santa_barbara_{tag}"
    assert sample_tree["goleta"].path == f"usa_{tag}.ca_{tag}.santa_barbara_{tag}.goleta_{tag}"


async def test_non_national_requires_a_parent(db_session):
    with pytest.raises(ValueError):
        await create_org_unit(db_session, level=OrgLevel.state, name="CA", slug=f"ca_{uuid.uuid4().hex[:8]}", parent=None)


async def test_national_cannot_have_a_parent(db_session):
    tag = uuid.uuid4().hex[:8]
    usa = await create_org_unit(db_session, level=OrgLevel.national, name="USA", slug=f"usa_{tag}")
    with pytest.raises(ValueError):
        await create_org_unit(
            db_session, level=OrgLevel.national, name="Bad", slug=f"bad_{tag}", parent=usa
        )


async def test_child_level_must_be_below_parent_level(db_session):
    tag = uuid.uuid4().hex[:8]
    usa = await create_org_unit(db_session, level=OrgLevel.national, name="USA", slug=f"usa_{tag}")
    with pytest.raises(ValueError):
        # a state cannot be the parent of another state
        ca = await create_org_unit(
            db_session, level=OrgLevel.state, name="CA", slug=f"ca_{tag}", parent=usa
        )
        await create_org_unit(db_session, level=OrgLevel.state, name="NV", slug=f"nv_{tag}", parent=ca)


async def test_get_subtree_returns_county_and_its_locals_only(db_session, sample_tree):
    subtree = await get_subtree(db_session, sample_tree["santa_barbara"].id)
    names = {u.name for u in subtree}
    assert names == {"Santa Barbara", "Goleta Club", "Montecito Club"}
    assert sample_tree["ventura"].name not in names


async def test_get_subtree_exclude_self(db_session, sample_tree):
    subtree = await get_subtree(db_session, sample_tree["santa_barbara"].id, include_self=False)
    names = {u.name for u in subtree}
    assert names == {"Goleta Club", "Montecito Club"}


async def test_get_ancestors_root_first(db_session, sample_tree):
    ancestors = await get_ancestors(db_session, sample_tree["goleta"].id)
    assert [a.name for a in ancestors] == ["USA", "California", "Santa Barbara"]


async def test_active_members_include_descendants(db_session, sample_tree, member_position):
    alice = Person(first_name="Alice", last_name="Nguyen")
    bob = Person(first_name="Bob", last_name="Ortiz")
    db_session.add_all([alice, bob])
    await db_session.flush()

    db_session.add_all(
        [
            Membership(
                person_id=alice.id,
                org_unit_id=sample_tree["goleta"].id,
                position_type_id=member_position.id,
            ),
            Membership(
                person_id=bob.id,
                org_unit_id=sample_tree["ventura"].id,
                position_type_id=member_position.id,
            ),
        ]
    )
    await db_session.flush()

    county_members = await get_active_members(
        db_session, sample_tree["santa_barbara"].id, include_descendants=True
    )
    assert [p.last_name for p in county_members] == ["Nguyen"]

    county_only = await get_active_members(
        db_session, sample_tree["santa_barbara"].id, include_descendants=False
    )
    assert county_only == []


async def test_one_active_club_membership_per_person(db_session, sample_tree, member_position):
    alice = Person(first_name="Alice", last_name="Nguyen")
    db_session.add(alice)
    await db_session.flush()

    db_session.add(
        Membership(
            person_id=alice.id,
            org_unit_id=sample_tree["goleta"].id,
            position_type_id=member_position.id,
        )
    )
    await db_session.flush()

    db_session.add(
        Membership(
            person_id=alice.id,
            org_unit_id=sample_tree["goleta"].id,
            position_type_id=member_position.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_membership_requires_exactly_one_target(db_session, sample_tree, member_position):
    alice = Person(first_name="Alice", last_name="Nguyen")
    db_session.add(alice)
    await db_session.flush()

    db_session.add(Membership(person_id=alice.id, position_type_id=member_position.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_move_unit_rewrites_own_and_descendant_paths(db_session, sample_tree):
    tag = sample_tree["tag"]
    await move_unit(db_session, sample_tree["goleta"].id, sample_tree["ventura"].id)
    await db_session.refresh(sample_tree["goleta"])
    assert sample_tree["goleta"].path == f"usa_{tag}.ca_{tag}.ventura_{tag}.goleta_{tag}"

    # Montecito, left behind under Santa Barbara, is untouched
    await db_session.refresh(sample_tree["montecito"])
    assert sample_tree["montecito"].path == f"usa_{tag}.ca_{tag}.santa_barbara_{tag}.montecito_{tag}"


async def test_move_unit_rejects_cycle(db_session, sample_tree):
    with pytest.raises(ValueError):
        await move_unit(db_session, sample_tree["ca"].id, sample_tree["goleta"].id)
