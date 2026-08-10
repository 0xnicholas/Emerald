"""PostgreSQL async session factory."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from emerald.config import get_settings


class SessionFactory:
    """Manages the async SQLAlchemy engine and session factory."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine = self._build_engine(database_url)
        self._sessionmaker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @staticmethod
    def _build_engine(database_url: str) -> AsyncEngine:
        """Build the engine; use NullPool under Celery workers (see rebuild_for_worker)."""
        kwargs: dict = {
            "echo": False,
            "pool_pre_ping": True,
        }
        if os.environ.get("EMERALD_CELERY_WORKER") == "1":
            # No connection may outlive the task's event loop.
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_size"] = 10
            kwargs["max_overflow"] = 20
        return create_async_engine(database_url, **kwargs)

    def rebuild_for_worker(self) -> None:
        """Swap in a connection-less engine for Celery worker processes.

        Every Celery task runs its async helpers in a fresh event loop
        (``run_async`` -> ``asyncio.run``).  A pooled asyncpg connection
        created in one task's loop cannot be reused by the next — the pool
        would hand it out and asyncpg raises "Event loop is closed" /
        "attached to a different loop".  NullPool gives every session a
        fresh connection created in the current task's loop.
        """
        old = self.engine
        self.engine = self._build_engine(self.database_url)
        self._sessionmaker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        if old is not None:
            # Best-effort: close pooled connections created before the fork.
            try:
                import asyncio

                asyncio.run(old.dispose())
            except Exception:
                pass

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()


# Singleton
settings = get_settings()
session_factory = SessionFactory(settings.database_url)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with session_factory.session() as session:
        yield session
