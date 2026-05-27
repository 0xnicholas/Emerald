"""API authentication dependencies."""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status

from emerald.config import get_settings
from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey


async def api_key_auth(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].startswith("em_"):
        raise HTTPException(401, "Missing or invalid API key")

    api_key = parts[1]
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    from sqlalchemy import select

    async with session_factory.session() as session:
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(401, "Invalid API key")

    if record.expires_at and record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "API key expired")

    request.state.api_key_id = str(record.id)
    request.state.entity_id = str(record.entity_id)
    request.state.permissions = record.permissions or []
    return "authenticated"


async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(403, "Write permission required")
    return "authorized"


def _get_endpoint_limit(endpoint: str) -> int:
    """Return per-endpoint request limit from settings."""
    settings = get_settings()
    if "/memories" in endpoint:
        return settings.rate_limit_memories
    if "/search" in endpoint:
        return settings.rate_limit_search
    if "/profiles" in endpoint:
        return settings.rate_limit_profiles
    if "/upload" in endpoint:
        return settings.rate_limit_upload
    return 60  # default


async def rate_limit(request: Request) -> None:
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return  # Auth hasn't run yet or failed

    # Use route pattern (e.g. /v1/pipelines/{pipeline_id}) instead of
    # full path so that path parameters don't create separate buckets.
    route = request.scope.get("route")
    endpoint = getattr(route, "path", None) if route else None
    if not endpoint:
        endpoint = request.url.path

    limit = _get_endpoint_limit(endpoint)
    window = 60  # 1 minute sliding window

    try:
        from emerald.db.redis import get_redis_client

        redis = get_redis_client()
    except RuntimeError:
        return  # Redis unavailable — skip rate limiting

    key = f"ratelimit:sliding:{key_id}:{endpoint}"
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex}"

    # Remove entries outside the sliding window
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window)
    pipe.zcard(key)
    _, current = await pipe.execute()

    if current >= limit:
        # Calculate approximate retry-after based on oldest member in window
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        retry_after = window
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = max(1, int(oldest_ts + window - now))
        raise HTTPException(
            429,
            "Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # Record this request and set TTL
    await redis.zadd(key, {member: now})
    await redis.expire(key, window)
