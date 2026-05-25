"""Redis integration tests — verify driver lifecycle with fakeredis."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_redis_state(monkeypatch):
    """Reset global Redis state and patch from_url to use fakeredis."""
    import fakeredis.aioredis as fake_aioredis

    import emerald.db.redis as redis_mod

    # Reset global client
    redis_mod._client = None

    def fake_from_url(url, **kwargs):
        return fake_aioredis.FakeRedis()

    monkeypatch.setattr(redis_mod.aioredis, "from_url", fake_from_url)

    yield

    # Cleanup
    redis_mod._client = None


@pytest.mark.asyncio
async def test_init_redis_creates_client():
    """init_redis() creates a connected client and get_redis_client() returns it."""
    from emerald.db.redis import close_redis, get_redis_client, init_redis

    await init_redis()
    client = get_redis_client()
    assert client is not None

    # Verify it works
    await client.set("test_key", "test_value")
    value = await client.get("test_key")
    assert value == b"test_value"

    await close_redis()


@pytest.mark.asyncio
async def test_get_redis_client_before_init_raises():
    """get_redis_client() raises RuntimeError before init_redis()."""
    from emerald.db.redis import get_redis_client

    with pytest.raises(RuntimeError, match="not initialized"):
        get_redis_client()


@pytest.mark.asyncio
async def test_close_redis_clears_client():
    """close_redis() clears the global client; subsequent get raises."""
    from emerald.db.redis import close_redis, get_redis_client, init_redis

    await init_redis()
    assert get_redis_client() is not None

    await close_redis()

    with pytest.raises(RuntimeError, match="not initialized"):
        get_redis_client()


@pytest.mark.asyncio
async def test_legacy_redis_client_wrapper():
    """RedisClient backward-compatible wrapper delegates to new lifecycle."""
    from emerald.db.redis import RedisClient, close_redis

    wrapper = RedisClient("redis://localhost:6379/0")

    await wrapper.connect()
    client = wrapper.client
    await client.set("legacy", "works")
    assert await client.get("legacy") == b"works"

    await wrapper.close()
    await close_redis()


@pytest.mark.asyncio
async def test_redis_client_ping_succeeds():
    """FakeRedis client responds to ping."""
    from emerald.db.redis import close_redis, get_redis_client, init_redis

    await init_redis()
    client = get_redis_client()
    assert await client.ping()

    await close_redis()
