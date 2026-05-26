"""API authentication dependencies."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status

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


async def rate_limit(request: Request) -> None:
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return  # Auth hasn't run yet or failed

    endpoint = request.url.path
    limit = 60  # Fixed-window: 60 requests per minute per endpoint

    try:
        from emerald.db.redis import get_redis_client

        redis = get_redis_client()
    except RuntimeError:
        return  # Redis unavailable — skip rate limiting

    key = f"ratelimit:{key_id}:{endpoint}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)
    if current > limit:
        raise HTTPException(
            429,
            "Rate limit exceeded",
            headers={"Retry-After": "60"},
        )
