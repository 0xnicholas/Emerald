"""OAuth state store — Redis-backed, multi-worker safe (P2.1 fix).

This was previously a module-level dict in
``emerald/api/routes/v1/connectors.py`` which broke any deployment
with more than one worker (the OAuth callback might land on a
different worker than the one that issued the ``/connect`` URL).
Moved here so the storage abstraction is testable in isolation
from the connector route.
"""

from __future__ import annotations

from redis.asyncio import Redis

from emerald.config import get_settings


class OAuthStateStore:
    """Redis-backed store for OAuth state tokens.

    Tokens are single-use: ``consume()`` deletes after read.
    The TTL is the upper bound on how long a user has to complete the
    provider's consent screen (default 10 minutes).
    """

    KEY_PREFIX = "emerald:oauth_state:"

    def __init__(self, ttl_seconds: int | None = None) -> None:
        # Default to the configured TTL so ops can tune it without code
        # changes. Tests can pass an explicit value to avoid the settings
        # lookup.
        if ttl_seconds is None:
            ttl_seconds = get_settings().oauth_state_ttl_seconds
        self.ttl_seconds = ttl_seconds

    @classmethod
    def _key(cls, token: str) -> str:
        return f"{cls.KEY_PREFIX}{token}"

    async def put(self, redis: Redis, token: str, entity_id: str) -> None:
        await redis.set(self._key(token), entity_id, ex=self.ttl_seconds)

    async def get(self, redis: Redis, token: str) -> str | None:
        return await redis.get(self._key(token))

    async def consume(self, redis: Redis, token: str) -> str | None:
        """Atomically read+delete the state token.

        Returns the entity_id that was bound to ``token``, or None if the
        token is missing or expired.  Uses ``GETDEL`` so two concurrent
        callbacks can never both succeed (the second one gets None).
        """
        # GETDEL is atomic in Redis 6.2+.  Falls back to a non-atomic
        # get+delete pair only if the redis-py client doesn't support
        # the method (older versions).
        if hasattr(redis, "getdel"):
            return await redis.getdel(self._key(token))
        # Fallback path: best-effort, not atomic.
        entity_id = await redis.get(self._key(token))
        if entity_id is None:
            return None
        await redis.delete(self._key(token))
        return entity_id
        entity_id = await redis.get(self._key(token))
        if entity_id is None:
            return None
        await redis.delete(self._key(token))
        return entity_id
