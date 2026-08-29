"""Tests for the Redis client lifecycle (per-event-loop rebinding)."""

import asyncio

import pytest


class _FakeRedis:
    def __init__(self, tag):
        self.tag = tag
        self._closed = False

    async def ping(self):
        return True

    async def aclose(self):
        self._closed = True


def _install_fake(monkeypatch, tag):
    from emerald import db
    import emerald.db.redis as redis_mod

    def _from_url(url, **kwargs):
        return _FakeRedis(tag)

    monkeypatch.setattr(redis_mod.aioredis, "from_url", _from_url)
    monkeypatch.setattr(redis_mod, "_client", None)
    monkeypatch.setattr(redis_mod, "_client_loop", None)
    return redis_mod


def test_ensure_redis_for_loop_rebinds_across_loops(monkeypatch):
    """A client created in one task's loop must be replaced in the next.

    Regression for P0-3: Celery tasks run each in a fresh event loop; the
    loop-mismatch check must not rely on ``id()`` of a destroyed loop
    (addresses can be reused), which returned the stale client and raised
    "got Future attached to a different loop".
    """
    redis_mod = _install_fake(monkeypatch, "first")

    first_id = {}

    async def _cycle_one():
        client = await redis_mod.ensure_redis_for_loop()
        first_id["loop"] = asyncio.get_running_loop()
        first_id["client"] = client
        return client

    asyncio.run(_cycle_one())

    # Simulate an id()-collision: destroy the first loop and verify the
    # strong-reference check still detects the change.
    second_id = {}

    async def _cycle_two():
        client = await redis_mod.ensure_redis_for_loop()
        second_id["loop"] = asyncio.get_running_loop()
        second_id["client"] = client
        return client

    asyncio.run(_cycle_two())

    assert first_id["loop"] is not second_id["loop"]
    # The strong loop reference keeps the first loop alive, so even if the
    # new loop happens to reuse the first loop's address, identity differs
    # and the client gets re-created for the current loop.
    assert first_id["client"] is not second_id["client"]


def test_ensure_redis_same_loop_returns_same_client(monkeypatch):
    """Within one loop (API process), the client is reused, not re-created."""
    redis_mod = _install_fake(monkeypatch, "stable")

    async def _cycle():
        c1 = await redis_mod.ensure_redis_for_loop()
        c2 = await redis_mod.ensure_redis_for_loop()
        return c1, c2

    c1, c2 = asyncio.run(_cycle())
    assert c1 is c2
