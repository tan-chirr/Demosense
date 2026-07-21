import pytest_asyncio
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demosense.api.main import app
from demosense.db import SessionLocal, engine
from demosense.models.person import Person, PositionType
from demosense.winloop import use_selector_event_loop_on_windows

use_selector_event_loop_on_windows()

SUPERUSER_EMAIL = "rbac-test-superuser@democlub.dev"
SUPERUSER_PASSWORD = "RbacTestSuper123!"


@pytest_asyncio.fixture
async def db_session():
    """A session bound to a transaction that is always rolled back.

    Service functions only flush(), never commit(), so wrapping the whole
    test in one outer transaction and rolling it back at the end is enough
    to keep tests isolated from each other and from real data.
    """
    async with engine.connect() as connection:
        trans = await connection.begin()
        session = AsyncSession(bind=connection)
        yield session
        await session.close()
        if trans.is_active:
            await trans.rollback()


@pytest_asyncio.fixture
async def member_position(db_session):
    # Real seed data (scripts/seed_position_types.py) may already have
    # committed a "member" row before this test's transaction started -
    # reuse it rather than colliding with the unique constraint on code.
    existing = (await db_session.scalars(select(PositionType).filter_by(code="member"))).one_or_none()
    if existing is not None:
        return existing
    position = PositionType(code="member", label="Member")
    db_session.add(position)
    await db_session.flush()
    return position


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def superuser_token(client):
    async with SessionLocal() as session:
        existing = (
            await session.scalars(select(Person).filter_by(email=SUPERUSER_EMAIL))
        ).one_or_none()
        if existing is None:
            session.add(
                Person(
                    email=SUPERUSER_EMAIL,
                    first_name="RBAC",
                    last_name="TestSuperuser",
                    hashed_password=PasswordHelper().hash(SUPERUSER_PASSWORD),
                    is_superuser=True,
                    is_verified=True,
                )
            )
            await session.commit()

    resp = await client.post(
        "/auth/jwt/login",
        data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
