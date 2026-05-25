"""Redis async client lifecycle."""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from emerald.config import get_settings

_client: Redis | None = None


async def init_redis() -> None:
    """Initialize the Redis async client."""
    global _client
    settings = get_settings()
    _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _client.ping()


async def close_redis() -> None:
    """Close the Redis async client."""
    global _client
    if _client:
        # redis-py 5.0+ prefers aclose(); fall back for older versions
        if hasattr(_client, "aclose"):
            await _client.aclose()
        else:
            await _client.close()
        _client = None


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
