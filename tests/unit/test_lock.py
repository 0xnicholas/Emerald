"""Tests for DistributedLock — Celery Beat deduplication."""

from __future__ import annotations

import asyncio

import pytest
import fakeredis.aioredis

from emerald.core.lock import DEFAULT_TTL_SECONDS, DistributedLock


@pytest.fixture
def fake_redis():
    """Provide a fakeredis instance patched into get_redis_client."""
    redis = fakeredis.aioredis.FakeRedis()
    return redis


@pytest.fixture
def patch_redis(monkeypatch, fake_redis):
    """Patch get_redis_client to return a fakeredis instance."""
    monkeypatch.setattr(
        "emerald.db.redis.get_redis_client",
        lambda: fake_redis,
    )
    return fake_redis


# ---- Basic lock lifecycle ----


@pytest.mark.asyncio
async def test_acquire_succeeds_on_first_attempt(patch_redis):
    """First acquisition of a lock succeeds."""
    lock = DistributedLock("test_basic")
    assert await lock.acquire() is True
    await lock.release()


@pytest.mark.asyncio
async def test_acquire_fails_when_held(patch_redis):
    """Second concurrent acquisition of the same lock fails."""
    lock1 = DistributedLock("test_contention")
    lock2 = DistributedLock("test_contention")

    assert await lock1.acquire() is True
    assert await lock2.acquire() is False

    await lock1.release()
    await lock2.release()  # no-op since not acquired


@pytest.mark.asyncio
async def test_reacquire_after_release(patch_redis):
    """After releasing, the lock can be acquired again."""
    lock1 = DistributedLock("test_reacquire")
    assert await lock1.acquire() is True
    await lock1.release()

    lock2 = DistributedLock("test_reacquire")
    assert await lock2.acquire() is True
    await lock2.release()


@pytest.mark.asyncio
async def test_different_locks_independent(patch_redis):
    """Different lock names don't conflict."""
    lock_a = DistributedLock("task_a")
    lock_b = DistributedLock("task_b")

    assert await lock_a.acquire() is True
    assert await lock_b.acquire() is True

    await lock_a.release()
    await lock_b.release()


# ---- TTL (auto-expiry) ----


@pytest.mark.asyncio
async def test_lock_auto_expires(patch_redis, fake_redis):
    """Lock expires after TTL, allowing re-acquisition."""
    lock1 = DistributedLock("test_ttl", ttl_seconds=1)
    assert await lock1.acquire() is True

    # Manually expire the key (simulating TTL expiry)
    await fake_redis.delete("emerald:lock:test_ttl")

    lock2 = DistributedLock("test_ttl")
    assert await lock2.acquire() is True
    await lock2.release()


# ---- Context manager ----


@pytest.mark.asyncio
async def test_context_manager_acquires_and_releases(patch_redis, fake_redis):
    """Using `async with` acquires and releases correctly."""
    async with DistributedLock("test_ctx") as lock:
        assert lock._acquired is True
        # Verify key exists in Redis
        assert await fake_redis.exists("emerald:lock:test_ctx") == 1

    # After context exit, lock should be released
    assert await fake_redis.exists("emerald:lock:test_ctx") == 0


@pytest.mark.asyncio
async def test_context_manager_contention_skips(patch_redis):
    """When lock is held, context manager still enters but is not acquired."""
    lock1 = DistributedLock("test_ctx_contention")
    await lock1.acquire()

    lock2 = DistributedLock("test_ctx_contention")
    acquired = await lock2.acquire()
    assert acquired is False
    assert lock2._acquired is False

    await lock1.release()


# ---- Atomic release (only own lock) ----


@pytest.mark.asyncio
async def test_cannot_release_others_lock(patch_redis, fake_redis):
    """A process cannot release a lock held by another process."""
    lock1 = DistributedLock("test_atomic", instance_id="worker-1")
    await lock1.acquire()

    # Simulate worker-2 trying to release worker-1's lock
    lock2 = DistributedLock("test_atomic", instance_id="worker-2")
    await lock2.release()  # Should be no-op (not acquired)

    # worker-1's lock should still exist
    key = "emerald:lock:test_atomic"
    assert await fake_redis.exists(key) == 1
    value = await fake_redis.get(key)
    if isinstance(value, bytes):
        value = value.decode()
    assert value == "worker-1"

    # worker-1 releases correctly
    await lock1.release()
    assert await fake_redis.exists(key) == 0


# ---- Redis unavailable (fail open) ----


@pytest.mark.asyncio
async def test_acquire_fails_open_when_redis_unavailable(monkeypatch):
    """When Redis is not initialised, lock acquisition succeeds (fail open)."""
    # Don't patch redis — RuntimeError from get_redis_client triggers fail-open
    lock = DistributedLock("test_fail_open")
    # acquire() catches RuntimeError and returns True
    assert await lock.acquire() is True
    # release() is a no-op
    await lock.release()


@pytest.mark.asyncio
async def test_release_noop_when_not_acquired():
    """Releasing an un-acquired lock does nothing."""
    # No redis available
    lock = DistributedLock("test_noop")
    await lock.release()  # Should not raise


# ---- Instance ID isolation ----


@pytest.mark.asyncio
async def test_different_instances_have_different_ids(patch_redis, fake_redis):
    """Two locks with different instance_ids don't interfere with release."""
    lock_a = DistributedLock("test_inst", instance_id="server-a:1234")
    lock_b = DistributedLock("test_inst", instance_id="server-b:5678")

    assert await lock_a.acquire() is True
    assert await lock_b.acquire() is False  # contended

    # server-b tries to release (should be no-op — didn't acquire)
    await lock_b.release()
    assert await fake_redis.exists("emerald:lock:test_inst") == 1

    # server-a releases
    await lock_a.release()
    assert await fake_redis.exists("emerald:lock:test_inst") == 0


# ---- Default TTL ----


def test_default_ttl_is_reasonable():
    """Default TTL should be long enough for tasks but not infinite."""
    assert DEFAULT_TTL_SECONDS >= 60
    assert DEFAULT_TTL_SECONDS <= 3600  # Max 1 hour
