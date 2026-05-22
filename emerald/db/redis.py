"""Redis client singleton."""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from emerald.config import get_settings


class RedisClient:
    """Async Redis client wrapper."""

    def __init__(self, redis_url: str) -> None:
        self._client: Redis | None = None
        self._redis_url = redis_url

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis client not initialised. Call connect() first.")
        return self._client

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


settings = get_settings()
redis_client = RedisClient(settings.redis_url)


async def get_redis() -> Redis:
    """FastAPI dependency for Redis client."""
    return redis_client.client
