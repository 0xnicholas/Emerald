"""Unit tests for API key authentication."""

import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from emerald.api.dependencies import api_key_auth, require_write_permission, rate_limit


class FakeRequest:
    def __init__(self, headers=None, state=None):
        self.headers = headers or {}
        self.state = state or type("State", (), {})()


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
    fake_record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
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
    """Rate limit allows requests under the limit."""
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()

    req = FakeRequest()
    req.state.api_key_id = "key_1"
    req.url = MagicMock()
    req.url.path = "/v1/memories"

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        await rate_limit(req)

    # Should not raise


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit():
    """Rate limit raises 429 when over the limit."""
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()
    # Pre-seed the counter to exceed limit
    await fake_redis.setex("ratelimit:key_1:/v1/memories", 60, "61")

    req = FakeRequest()
    req.state.api_key_id = "key_1"
    req.url = MagicMock()
    req.url.path = "/v1/memories"

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        with pytest.raises(HTTPException) as exc_info:
            await rate_limit(req)

    assert exc_info.value.status_code == 429
