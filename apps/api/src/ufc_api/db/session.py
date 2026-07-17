"""Async database session construction, activated when the schema is introduced."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ufc_api.core.config import Settings


def build_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory only when a database URL is configured."""

    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required to create a database session factory")
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Provide one short transaction boundary for a future application use case."""

    async with factory.begin() as session:
        yield session
