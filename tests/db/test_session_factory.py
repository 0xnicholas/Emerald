"""Tests for the PostgreSQL session factory (worker pool semantics)."""

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from emerald.db.session import SessionFactory


def test_default_engine_uses_pooling(monkeypatch):
    monkeypatch.delenv("EMERALD_CELERY_WORKER", raising=False)
    factory = SessionFactory("postgresql+asyncpg://u:p@localhost:5432/db")

    assert isinstance(factory.engine.pool, AsyncAdaptedQueuePool)
    assert factory.engine.pool.size() == 10


def test_worker_flag_builds_nullpool(monkeypatch):
    """Celery workers must not reuse asyncpg connections across event loops."""
    monkeypatch.setenv("EMERALD_CELERY_WORKER", "1")
    factory = SessionFactory("postgresql+asyncpg://u:p@localhost:5432/db")

    assert isinstance(factory.engine.pool, NullPool)


def test_rebuild_for_worker_swaps_to_nullpool(monkeypatch):
    """An engine built before the fork (pooled) is swapped to NullPool."""
    monkeypatch.delenv("EMERALD_CELERY_WORKER", raising=False)
    factory = SessionFactory("postgresql+asyncpg://u:p@localhost:5432/db")
    assert isinstance(factory.engine.pool, AsyncAdaptedQueuePool)

    monkeypatch.setenv("EMERALD_CELERY_WORKER", "1")
    factory.rebuild_for_worker()

    assert isinstance(factory.engine.pool, NullPool)
