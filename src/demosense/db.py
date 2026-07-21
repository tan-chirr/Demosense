from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from demosense.config import settings


class Base(DeclarativeBase):
    pass


# pool_pre_ping: Neon (serverless Postgres) can terminate idle pooled
# connections when its compute suspends - pre_ping tests each connection
# before use and transparently reconnects instead of surfacing a stale
# "AdminShutdown"/"terminating connection" error to the caller.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
