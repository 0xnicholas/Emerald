"""API authentication dependencies."""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from emerald.config import get_settings
from emerald.core.session import SessionManager
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

    if record.expires_at and record.expires_at < datetime.now(UTC):
        raise HTTPException(401, "API key expired")

    request.state.api_key_id = str(record.id)
    request.state.entity_id = str(record.entity_id)
    request.state.permissions = record.permissions or []
    return "authenticated"


def authorize_entity(request: Request, entity_id: str) -> None:
    """Ensure the API key is scoped to the target entity.

    Centralized helper (N5) so memories / search / profiles / conflicts /
    upload / batch routes all enforce the same per-entity isolation check.
    Raises 403 if the authenticated entity is different from ``entity_id``.

    If ``request.state.entity_id`` is unset (e.g. in test fixtures that
    bypass auth), the check is a no-op so tests can use generic clients.
    """
    allowed = getattr(request.state, "entity_id", None)
    if allowed and allowed != entity_id:
        raise HTTPException(
            status_code=403,
            detail="Entity not authorized for this API key",
        )


async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(403, "Write permission required")
    return "authorized"


async def require_admin_permission(request: Request) -> str:
    """Management-surface guard (issue #5): only admin keys may create /
    list / revoke API keys.  Entity scoping is enforced separately by
    ``authorize_entity`` at the route layer."""
    perms = getattr(request.state, "permissions", [])
    if "admin" not in perms:
        raise HTTPException(403, "Admin permission required")
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


async def session_scope(request: Request) -> dict | None:
    """Optional session scope from ``X-Session-Token`` header.

    If the header is present, the token is validated and its claims (entity_id,
    project_id, session_id) are stored on ``request.state.session_claims``.
    Missing or invalid tokens raise 401.
    """
    token = request.headers.get("X-Session-Token")
    if not token:
        return None

    try:
        claims = SessionManager().decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    request.state.session_claims = claims
    return claims


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

    # Store rate limit metadata for X-RateLimit-* headers middleware
    request.state.rate_limit_limit = limit
    request.state.rate_limit_remaining = max(0, limit - int(current) - 1)
    request.state.rate_limit_reset = int(now + window)
