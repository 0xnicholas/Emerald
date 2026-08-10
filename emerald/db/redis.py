"""Redis async client lifecycle."""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from redis.asyncio import Redis

from emerald.config import get_settings

_client: Redis | None = None
# Event loop the current client is bound to.  redis.asyncio connections are
# loop-bound; Celery tasks each run in a fresh loop (run_async), so a client
# created in one task's loop must not be reused by the next.  Kept as a
# strong reference — ``id()`` of a destroyed loop can be reused by the next
# loop, which would defeat the loop-mismatch check.
_client_loop: asyncio.AbstractEventLoop | None = None


async def init_redis() -> None:
    """Initialize the Redis async client (bound to the current event loop)."""
    global _client, _client_loop
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        # Never leave a broken (unpinged) client in place: callers rely on
        # get_redis_client() raising RuntimeError when Redis is unavailable.
        await client.aclose()
        raise
    _client = client
    _client_loop = asyncio.get_running_loop()


async def ensure_redis_for_loop() -> Redis:
    """Return a Redis client bound to the *current* event loop.

    Used by Celery tasks, which execute their async helpers in a fresh
    event loop per invocation (``run_async`` -> ``asyncio.run``).  If the
    cached client belongs to a different (possibly dead) loop, re-initialize
    it in the current loop.
    """
    global _client
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        await init_redis()
    return _client  # type: ignore[return-value]


async def close_redis() -> None:
    """Close the Redis async client."""
    global _client, _client_loop
    if _client:
        # redis-py 5.0+ prefers aclose(); fall back for older versions
        if hasattr(_client, "aclose"):
            await _client.aclose()
        else:
            await _client.close()
        _client = None
        _client_loop = None


def get_redis_client() -> Redis:
    """Return the initialized Redis client.

    Raises RuntimeError if init_redis() has not been called.
    """
    if _client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _client


# Legacy wrapper for backwards compatibility
class RedisClient:
    """Async Redis client wrapper (legacy)."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    @property
    def client(self) -> Redis:
        return get_redis_client()

    async def connect(self) -> None:
        await init_redis()

    async def close(self) -> None:
        await close_redis()


settings = get_settings()
redis_client = RedisClient(settings.redis_url)


async def get_redis() -> Redis:
    """FastAPI dependency for Redis client."""
    return get_redis_client()
