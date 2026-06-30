"""Tests for OAuth state storage (P2.1 fix).

P2.1 fix: the OAuth callback flow used an in-process dict to hold state
tokens, breaking multi-worker / multi-pod deployments because the OAuth
callback might land on a different worker than the one that issued the
``/connect`` URL.  Production must use Redis with a TTL (10 minutes).

These tests pin the contract: the state store is a thin wrapper that
stores ``state_token → entity_id`` in Redis with an expiry.  When Redis
is unavailable, the store MUST raise rather than silently fall back to
an in-memory dict \u2014 silent fallback would re-introduce the bug.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------- Behavior contract ----------

def test_state_store_module_exists():
    from emerald.api.routes.v1 import connectors as conn
    assert hasattr(conn, "OAuthStateStore"), (
        "Connectors module must export OAuthStateStore"
    )


def test_state_store_uses_redis_with_ttl():
    """state_token → entity_id mapping must be stored in Redis with a TTL."""
    from emerald.api._state_store import OAuthStateStore

    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock(return_value=True)

    async def run():
        await store.put(fake_redis, "state_abc", "user_123")

    asyncio.run(run())

    fake_redis.set.assert_awaited_once()
    call = fake_redis.set.call_args
    # Signature: redis.set(name, value, ex=...)
    assert call.args[0] == "emerald:oauth_state:state_abc"
    assert call.args[1] == "user_123"
    # TTL must be passed via ex=...
    assert call.kwargs.get("ex") == 600, (
        f"OAuth state MUST have a TTL (got {call.kwargs})"
    )


def test_state_store_get_returns_entity_id():
    from emerald.api._state_store import OAuthStateStore

    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value="user_alice")

    async def run():
        return await store.get(fake_redis, "state_abc")

    assert asyncio.run(run()) == "user_alice"


def test_state_store_consume_deletes_token():
    """state tokens are single-use: consume() must delete them after lookup."""
    from emerald.api._state_store import OAuthStateStore

    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(return_value="user_alice")

    async def run():
        return await store.consume(fake_redis, "state_abc")

    assert asyncio.run(run()) == "user_alice"
    fake_redis.getdel.assert_awaited_once_with("emerald:oauth_state:state_abc")


def test_state_store_consume_returns_none_for_missing_token():
    """Missing/expired token must return None (not raise)."""
    from emerald.api._state_store import OAuthStateStore

    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(return_value=None)

    async def run():
        return await store.consume(fake_redis, "state_expired")

    assert asyncio.run(run()) is None


def test_state_store_raises_when_redis_unavailable():
    """Redis errors must propagate \u2014 silent fallback to in-memory is the bug.

    P2.1: the previous in-memory dict fallback broke multi-worker setups.
    The whole point of the fix is that we use Redis, so if Redis is down
    the OAuth flow fails loudly (returning 503) rather than silently
    accepting tokens that won't work across workers.
    """
    from emerald.api._state_store import OAuthStateStore

    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(side_effect=ConnectionError("redis down"))

    async def run():
        return await store.consume(fake_redis, "state_abc")

    with pytest.raises(ConnectionError):
        asyncio.run(run())


# ---------- Integration with the connector route ----------

def test_connect_provider_uses_redis_not_module_dict():
    """The /connect endpoint must persist state in Redis, not the
    module-level _oauth_state_store dict.
    """
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    from emerald.api.routes.v1 import connectors as conn

    # Sanity: the in-memory dict must be removed (or at minimum not
    # referenced by the route).  This is a heuristic: if the route
    # imports / mutates _oauth_state_store, fail.
    with open(conn.__file__) as f:
        src = f.read()
    # The old pattern was: _oauth_state_store[state_token] = entity_id
    assert "_oauth_state_store[" not in src, (
        "Connector route must not write to module-level _oauth_state_store dict. "
        "Use OAuthStateStore with Redis instead."
    )
    # And the new pattern should reference OAuthStateStore
    assert "OAuthStateStore" in src, (
        "Connector route must use the OAuthStateStore abstraction"
    )


def test_oauth_state_store_namespace_is_namespaced():
    """The Redis key MUST be prefixed so it doesn't collide with other
    state stored by Emerald (idempotency keys, fast lane, etc.).
    """
    from emerald.api._state_store import OAuthStateStore
    store = OAuthStateStore(ttl_seconds=60)
    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock(return_value=True)

    async def run():
        await store.put(fake_redis, "tok", "u1")

    asyncio.run(run())
    call = fake_redis.set.call_args
    key = call.args[0]
    assert key.startswith("emerald:"), (
        f"Redis key must be namespaced under 'emerald:' (got {key!r})"
    )


# ---------- I1: GETDEL atomicity ----------

def test_consume_uses_atomic_getdel():
    """The store must use Redis's atomic GETDEL, not get+delete.

    Why: a non-atomic get+delete lets two concurrent callbacks both
    pass the auth check before either deletes the token.  GETDEL is
    a single Redis command, so the second callback sees None.
    """
    from emerald.api._state_store import OAuthStateStore
    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(return_value="user_alice")

    async def run():
        return await store.consume(fake_redis, "state_abc")

    assert asyncio.run(run()) == "user_alice"
    fake_redis.getdel.assert_awaited_once_with("emerald:oauth_state:state_abc")
    # The fallback get+delete must NOT have been called.
    fake_redis.get.assert_not_called()
    fake_redis.delete.assert_not_called()


def test_consume_falls_back_when_getdel_unavailable():
    """Older redis-py versions may not expose getdel; fallback to get+delete.

    This keeps the code portable.  The fallback is documented as non-atomic
    in the docstring so callers know the implication.
    """
    from emerald.api._state_store import OAuthStateStore
    store = OAuthStateStore(ttl_seconds=600)
    fake_redis = AsyncMock(spec=["get", "delete"])  # no getdel attr
    fake_redis.get = AsyncMock(return_value="user_alice")
    fake_redis.delete = AsyncMock(return_value=1)

    async def run():
        return await store.consume(fake_redis, "state_abc")

    assert asyncio.run(run()) == "user_alice"
    fake_redis.get.assert_awaited_once()
    fake_redis.delete.assert_awaited_once()


# ---------- I6: runtime 503 on Redis failure ----------

def test_redis_failure_returns_503_not_silent_fallback():
    """If the Redis client is uninitialised, /connect must return 503.

    Why: the original in-memory fallback silently broke multi-worker
    setups.  The whole point of the P2.1 fix is to fail loudly so ops
    notices.  This runtime test exercises the actual route, not just
    the source code patterns.

    We call the function directly (not via TestClient) because the
    OpenTelemetry FastAPI instrumentator produces spurious 422s in
    tests (see test_list_files.py for the same workaround).
    """
    import asyncio
    from unittest.mock import AsyncMock

    from fastapi import Request

    from emerald.api.routes.v1 import connectors as conn

    # Build a mock request with a known entity.
    mock_request = MagicMock(spec=Request)
    mock_request.state.entity_id = "user_alice"
    mock_request.state.api_key_id = "k"
    mock_request.state.permissions = ["read", "write"]
    mock_request.state.request_id = "test"

    # Mock the connector registry so we don't need real OAuth creds.
    fake_connector = MagicMock()
    fake_connector.get_auth_url = AsyncMock(
        return_value=("https://example.com/auth?state=abc", "state_abc"),
    )
    fake_registry = MagicMock()
    fake_registry.get.return_value = lambda entity_id: fake_connector

    # Force Redis to look uninitialised.
    import emerald.db.redis as redis_mod
    with patch.object(redis_mod, "get_redis_client",
                      side_effect=RuntimeError("redis not init")), \
         patch.object(conn, "get_connector_registry", return_value=fake_registry):
        async def run():
            return await conn.connect_provider(
                provider="google_drive", request=mock_request, redirect_uri=""
            )

        with pytest.raises(HTTPException) as info:
            asyncio.run(run())

    assert info.value.status_code == 503, (
        f"Expected 503 when Redis is down, got {info.value.status_code}: {info.value.detail}"
    )
    msg = (info.value.detail or "").lower()
    assert "redis" in msg or "unavailable" in msg, (
        f"503 message should mention Redis or 'unavailable', got: {info.value.detail}"
    )


# ---------- I8: TTL from settings ----------

def test_default_ttl_comes_from_settings():
    """OAuthStateStore() with no args reads ttl from Settings."""
    from emerald.api._state_store import OAuthStateStore
    from emerald.config import get_settings
    store = OAuthStateStore()
    assert store.ttl_seconds == get_settings().oauth_state_ttl_seconds


def test_default_ttl_uses_non_default_settings_value(monkeypatch):
    """The store MUST read the setting at construction time, not hardcode 600.

    Why: I8 regression.  If someone replaces the get_settings() call
    with ``self.ttl_seconds = 600``, this test still passes when the
    setting's default is also 600 (false negative).  Setting the
    setting to a different value via monkeypatch proves the read path
    is actually exercised.
    """
    # Build a Settings instance with a non-default value, then patch
    # get_settings() to return it.  This bypasses the lru_cache so the
    # override is guaranteed to take effect.
    from emerald.config import Settings
    custom_settings = Settings(
        _env_file=None,
        oauth_state_ttl_seconds=300,
    )
    assert custom_settings.oauth_state_ttl_seconds == 300, (
        "Sanity: the test override failed — env or default leaking through"
    )

    from emerald.api import _state_store
    original_get_settings = _state_store.get_settings
    _state_store.get_settings = lambda: custom_settings
    try:
        # Force re-import to pick up the patched get_settings
        store = _state_store.OAuthStateStore()
    finally:
        _state_store.get_settings = original_get_settings

    assert store.ttl_seconds == 300, (
        f"OAuthStateStore must read oauth_state_ttl_seconds from settings, "
        f"got {store.ttl_seconds} (expected 300 from the test override). "
        f"If this is 600, the constructor is hardcoding the value."
    )


def test_explicit_ttl_overrides_settings():
    """An explicit ttl_seconds argument wins over the settings default."""
    from emerald.api._state_store import OAuthStateStore
    store = OAuthStateStore(ttl_seconds=120)
    assert store.ttl_seconds == 120


def test_settings_default_is_600_seconds():
    """Default oauth_state_ttl_seconds is 10 minutes (OAuth round-trip budget)."""
    from emerald.config import Settings
    s = Settings(_env_file=None)
    assert s.oauth_state_ttl_seconds == 600
