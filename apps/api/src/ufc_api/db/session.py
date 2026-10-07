"""Async database session construction, activated when the schema is introduced."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
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


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a managed async database session from the application session factory."""

    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "session_factory", None
    )
    if factory is None:
        from ufc_api.core.errors import DomainError

        raise DomainError(
            code="database_unavailable",
            message="Database connection is not configured or unavailable.",
            status_code=503,
            retryable=True,
        )
    async with factory() as session:
        yield session


async def get_optional_db_session(request: Request) -> AsyncIterator[AsyncSession | None]:
    """Yield a database session if configured and reachable, otherwise yield None for fallback."""

    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "session_factory", None
    )
    if factory is None:
        yield None
        return
    try:
        async with factory() as session:
            yield session
    except Exception:
        yield None
