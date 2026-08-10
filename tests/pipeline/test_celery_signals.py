"""Tests for Celery worker lifecycle signal wiring."""

import pytest

from emerald.pipeline.celery import _dispose_db_pool_before_task


def test_task_prerun_disposes_shared_pool(monkeypatch):
    """Every Celery task must get a pool emptied of the previous task's
    connections.

    Regression for P0-3: each task runs its async helpers in a fresh event
    loop (``run_async`` -> ``asyncio.run``); reusing a pooled asyncpg
    connection created in a previous task's loop raises "Event loop is
    closed" / "attached to a different loop".
    """
    disposed = []

    class _Engine:
        async def dispose(self):
            disposed.append(True)

    class _Factory:
        engine = _Engine()

    monkeypatch.setattr("emerald.db.session.session_factory", _Factory())

    _dispose_db_pool_before_task(task_id="t-1", task=object(), args=(), kwargs={})

    assert disposed == [True]


def test_task_prerun_signal_is_registered():
    """The dispose handler is actually connected to celery's task_prerun."""
    import weakref

    from celery import signals as celery_signals

    names = []
    for item in celery_signals.task_prerun.receivers:
        # receivers are (key, weakref-or-receiver) pairs in celery 5.x
        ref = item[-1]
        recv = ref() if isinstance(ref, weakref.ReferenceType) else ref
        names.append(getattr(recv, "__name__", None))
    assert "_dispose_db_pool_before_task" in names


def test_worker_process_init_signal_is_registered():
    """The worker init handler is connected to celery's worker_process_init."""
    import weakref

    from celery import signals as celery_signals

    names = []
    for item in celery_signals.worker_process_init.receivers:
        ref = item[-1]
        recv = ref() if isinstance(ref, weakref.ReferenceType) else ref
        names.append(getattr(recv, "__name__", None))
    assert "_init_worker_process" in names
