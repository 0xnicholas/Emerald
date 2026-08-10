"""Unit tests for API key authentication."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission


class FakeRequest:
    def __init__(self, headers=None, state=None, url_path="/v1/memories"):
        self.headers = headers or {}
        self.state = state or type("State", (), {})()
        self.url = MagicMock()
        self.url.path = url_path
        self.scope = {"route": None}


@pytest.mark.asyncio
async def test_missing_header_returns_401():
    req = FakeRequest(headers={})
    with pytest.raises(HTTPException) as exc_info:
        await api_key_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_key_returns_401():
    req = FakeRequest(headers={"Authorization": "Bearer bad_key"})
    with pytest.raises(HTTPException) as exc_info:
        await api_key_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_with_db_record_authenticates():
    """Valid key with matching DB record → authenticated + state populated."""
    import uuid

    req = FakeRequest(headers={"Authorization": "Bearer em_validkey"})

    fake_record = MagicMock()
    fake_record.id = uuid.uuid4()
    fake_record.entity_id = uuid.uuid4()
    fake_record.permissions = ["read", "write"]
    fake_record.expires_at = None
    fake_record.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_record

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("emerald.api.dependencies.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_factory.session.return_value.__aexit__ = AsyncMock(
            return_value=False
        )
        result = await api_key_auth(req)

    assert result == "authenticated"
    assert getattr(req.state, "permissions", []) == ["read", "write"]
    assert hasattr(req.state, "entity_id")
    assert hasattr(req.state, "api_key_id")


@pytest.mark.asyncio
async def test_expired_key_returns_401():
    """Expired API key → 401."""
    import uuid

    req = FakeRequest(headers={"Authorization": "Bearer em_expired"})

    fake_record = MagicMock()
    fake_record.id = uuid.uuid4()
    fake_record.entity_id = uuid.uuid4()
    fake_record.permissions = ["read"]
    fake_record.expires_at = datetime.now(UTC) - timedelta(days=1)
    fake_record.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_record

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("emerald.api.dependencies.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_factory.session.return_value.__aexit__ = AsyncMock(
            return_value=False
        )
        with pytest.raises(HTTPException) as exc_info:
            await api_key_auth(req)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_write_permission_required():
    """require_write_permission raises 403 when write is missing."""
    req = FakeRequest()
    req.state.permissions = ["read"]

    with pytest.raises(HTTPException) as exc_info:
        await require_write_permission(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_write_permission_granted():
    """require_write_permission passes when write is present."""
    req = FakeRequest()
    req.state.permissions = ["read", "write"]

    result = await require_write_permission(req)
    assert result == "authorized"


@pytest.mark.asyncio
async def test_rate_limit_allows_under_limit():
    """Sliding-window rate limit allows requests under the limit."""

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()

    req = FakeRequest()
    req.state.api_key_id = "key_1"
    req.url = MagicMock()
    req.url.path = "/v1/memories"

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        await rate_limit(req)

    # Verify entry was recorded as sorted-set member
    key = "ratelimit:sliding:key_1:/v1/memories"
    count = await fake_redis.zcard(key)
    assert count == 1


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit():
    """Sliding-window rate limit raises 429 when over the limit."""
    import time

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()
    now = time.time()
    key = "ratelimit:sliding:key_1:/v1/memories"
    limit = 60  # default for /memories

    # Pre-seed the sorted set with exactly 'limit' entries inside the window
    members = {f"{now - i * 0.1}:{i}": now - i * 0.1 for i in range(limit)}
    await fake_redis.zadd(key, members)
    await fake_redis.expire(key, 60)

    req = FakeRequest()
    req.state.api_key_id = "key_1"
    req.url = MagicMock()
    req.url.path = "/v1/memories"

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        with pytest.raises(HTTPException) as exc_info:
            await rate_limit(req)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_rate_limit_uses_endpoint_specific_limits():
    """Different endpoints use different limits from settings."""
    import time

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()
    now = time.time()

    # /upload has limit=10 — seed 10 entries
    upload_key = "ratelimit:sliding:key_1:/v1/upload"
    members = {f"{now - i * 0.1}:{i}": now - i * 0.1 for i in range(10)}
    await fake_redis.zadd(upload_key, members)
    await fake_redis.expire(upload_key, 60)

    req = FakeRequest()
    req.state.api_key_id = "key_1"
    req.url = MagicMock()
    req.url.path = "/v1/upload"

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        with pytest.raises(HTTPException) as exc_info:
            await rate_limit(req)

    assert exc_info.value.status_code == 429


# ---- Admin permission + revoked-key auth (issue #5) ----

@pytest.mark.asyncio
async def test_admin_permission_required():
    """require_admin_permission raises 403 without the admin permission."""
    from emerald.api.dependencies import require_admin_permission

    req = FakeRequest()
    req.state.permissions = ["read", "write"]

    with pytest.raises(HTTPException) as exc_info:
        await require_admin_permission(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_permission_granted():
    """require_admin_permission passes when admin is present."""
    from emerald.api.dependencies import require_admin_permission

    req = FakeRequest()
    req.state.permissions = ["read", "write", "admin"]

    result = await require_admin_permission(req)
    assert result == "authorized"


@pytest.mark.asyncio
async def test_revoked_key_returns_401():
    """A revoked key is rejected because the auth query filters
    is_active=True — the record never comes back (issue #5)."""
    req = FakeRequest(headers={"Authorization": "Bearer em_revoked"})

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # revoked → DB miss

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("emerald.api.dependencies.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_factory.session.return_value.__aexit__ = AsyncMock(
            return_value=False
        )
        with pytest.raises(HTTPException) as exc_info:
            await api_key_auth(req)

    assert exc_info.value.status_code == 401
    # The revocation mechanism must be the is_active filter in the query.
    statement = str(mock_session.execute.call_args[0][0])
    assert "is_active" in statement
    assert "true" in statement.lower()
