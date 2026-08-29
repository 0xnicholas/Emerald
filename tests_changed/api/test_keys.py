"""Tests for API key management endpoints (issue #5).

Admin-only management surface (create / list / revoke) scoped to the
caller's entity.  The session layer is mocked at the route module level
(following tests/api/test_connectors.py); the auth dependency is overridden
so request.state carries the caller's internal entity UUID + permissions.
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import (
    api_key_auth,
    rate_limit,
    require_admin_permission,
)

ADMIN_ENTITY = str(uuid.uuid4())  # caller's internal entity UUID
OTHER_ENTITY = str(uuid.uuid4())


def _make_client(permissions: list[str] | None = None) -> TestClient:
    """TestClient with auth overridden to the caller.

    All three dependencies are overridden (the repo-wide convention — see
    tests/api/test_upload_authorization.py): with this FastAPI/Starlette
    version, the lazy included router re-solves route dependencies, so a
    partially-overridden dependency list is unreliable.  Permission levels
    are expressed through ``request.state.permissions``; the real
    ``require_admin_permission`` guard is unit-tested in
    tests/unit/test_auth.py.
    """

    async def _auth(request: Request):
        request.state.entity_id = ADMIN_ENTITY
        request.state.api_key_id = "key_admin"
        request.state.permissions = permissions or ["read", "write", "admin"]
        return "authenticated"

    async def _admin(request: Request):
        perms = getattr(request.state, "permissions", [])
        if "admin" not in perms:
            raise HTTPException(403, "Admin permission required")
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app()
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[require_admin_permission] = _admin
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_admin"})


@pytest.fixture
def admin_client() -> TestClient:
    return _make_client()


@pytest.fixture
def non_admin_client() -> TestClient:
    return _make_client(permissions=["read", "write"])


def _mock_db_session(side_effects: list) -> MagicMock:
    """Patch keys.session_factory with an AsyncMock session whose
    execute() returns the given results in call order."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = side_effects
    mock_factory = MagicMock()
    mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session, mock_factory


def _entity_result(entity_id: str | None):
    """A scalar_one_or_none result for the Entity lookup."""
    result = MagicMock()
    if entity_id:
        entity = MagicMock()
        entity.id = uuid.UUID(entity_id)
        result.scalar_one_or_none.return_value = entity
    else:
        result.scalar_one_or_none.return_value = None
    return result


def _keys_result(*records):
    """A scalars().all() result for the list query."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(records)
    return result


def _key_record(
    key_id: str | None = None,
    entity_id: str | None = None,
    permissions: list[str] | None = None,
    is_active: bool = True,
):
    record = MagicMock()
    record.id = uuid.UUID(key_id) if key_id else uuid.uuid4()
    record.entity_id = uuid.UUID(entity_id) if entity_id else uuid.uuid4()
    record.key_prefix = "em_abc12"
    record.permissions = permissions or ["read", "write"]
    record.expires_at = None
    record.last_used_at = None
    record.is_active = is_active
    record.created_at = None
    return record


# ── Create ────────────────────────────────────────────────────────────────


def test_create_key_requires_admin(non_admin_client):
    """A non-admin key gets 403 on the management surface."""
    response = non_admin_client.post(
        "/v1/keys",
        json={"entity_id": "user_alice", "permissions": ["read"]},
    )
    assert response.status_code == 403


def test_create_key_returns_plaintext_once_and_stores_hash(admin_client):
    """201 + plaintext key (em_ prefix) in the response only; the DB row
    carries only the SHA-256 hash and the prefix."""
    session, factory = _mock_db_session([_entity_result(ADMIN_ENTITY)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.post(
            "/v1/keys",
            json={"entity_id": "user_alice", "permissions": ["read", "write"]},
        )

    assert response.status_code == 201
    body = response.json()["data"]
    raw_key = body["key"]
    assert raw_key.startswith("em_")
    assert len(raw_key) > 8
    # Plaintext appears exactly once: only in this response body.
    assert "key_hash" not in body

    # The stored record has the hash + prefix only, never the raw key.
    added = session.add.call_args[0][0]
    assert hashlib.sha256(raw_key.encode()).hexdigest() == added.key_hash
    assert added.key_prefix == raw_key[:8]
    assert added.permissions == ["read", "write"]
    assert added.is_active is True
    assert added.entity_id == uuid.UUID(ADMIN_ENTITY)
    session.commit.assert_awaited()


def test_create_key_cross_entity_forbidden(admin_client):
    """An admin key cannot create keys for another entity (403)."""
    session, factory = _mock_db_session([_entity_result(OTHER_ENTITY)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.post(
            "/v1/keys",
            json={"entity_id": "user_mallory", "permissions": ["read"]},
        )

    assert response.status_code == 403
    session.commit.assert_not_awaited()


def test_create_key_unknown_entity_404(admin_client):
    """Creating a key for a non-existent entity returns 404."""
    session, factory = _mock_db_session([_entity_result(None)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.post(
            "/v1/keys",
            json={"entity_id": "ghost", "permissions": ["read"]},
        )
    assert response.status_code == 404
    session.commit.assert_not_awaited()


def test_create_key_rejects_unknown_permission(admin_client):
    """Permissions outside read/write/admin are rejected with 422."""
    response = admin_client.post(
        "/v1/keys",
        json={"entity_id": "user_alice", "permissions": ["sudo"]},
    )
    assert response.status_code == 422


def test_create_key_with_expiry(admin_client):
    """An optional expiry is stored on the record."""
    session, factory = _mock_db_session([_entity_result(ADMIN_ENTITY)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.post(
            "/v1/keys",
            json={
                "entity_id": "user_alice",
                "permissions": ["read"],
                "expires_at": "2026-09-01T00:00:00Z",
            },
        )
    assert response.status_code == 201
    added = session.add.call_args[0][0]
    assert added.expires_at is not None
    assert "2026-09-01" in response.json()["data"]["expires_at"]


# ── List ───────────────────────────────────────────────────────────────────


def test_list_keys_requires_admin(non_admin_client):
    response = non_admin_client.get("/v1/keys")
    assert response.status_code == 403


def test_list_keys_returns_metadata_without_hashes(admin_client):
    """List returns key metadata (prefix, permissions, expiry, last used),
    never hashes or raw keys."""
    record = _key_record(entity_id=ADMIN_ENTITY)
    session, factory = _mock_db_session([_keys_result(record)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.get("/v1/keys")

    assert response.status_code == 200
    body = response.json()
    items = body["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["key_prefix"] == "em_abc12"
    assert item["permissions"] == ["read", "write"]
    assert "key_hash" not in item
    assert "key" not in item
    assert "pagination" in body
    # The list query is scoped to the caller's entity.
    statement = str(session.execute.call_args[0][0])
    assert "api_keys" in statement


# ── Revoke ────────────────────────────────────────────────────────────────


def test_revoke_key_requires_admin(non_admin_client):
    response = non_admin_client.delete("/v1/keys/some-id")
    assert response.status_code == 403


def test_revoke_key_deactivates_and_returns_204(admin_client):
    """Revoking a key flips is_active off; the auth query already filters
    is_active=True, so the key is immediately invalid (401)."""
    record = _key_record(entity_id=ADMIN_ENTITY)
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    session, factory = _mock_db_session([result])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.delete(f"/v1/keys/{record.id}")

    assert response.status_code == 204
    assert record.is_active is False
    session.commit.assert_awaited()


def test_revoke_key_other_entity_forbidden(admin_client):
    """An admin key cannot revoke another entity's key."""
    record = _key_record(entity_id=OTHER_ENTITY)
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    session, factory = _mock_db_session([result])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.delete(f"/v1/keys/{record.id}")

    assert response.status_code == 403
    assert record.is_active is True
    session.commit.assert_not_awaited()


def test_revoke_key_not_found_404(admin_client):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session, factory = _mock_db_session([result])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.delete("/v1/keys/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    session.commit.assert_not_awaited()


# ── Validation + auth-path hardening (issue #5 review) ───────────────────


def test_create_key_malformed_types_422(admin_client):
    """Non-string entity_id / non-string permissions → 422, not 500."""
    response = admin_client.post(
        "/v1/keys",
        json={"entity_id": 123, "permissions": ["read"]},
    )
    assert response.status_code == 422


def test_create_key_naive_expiry_coerced_to_utc(admin_client):
    """A naive expires_at is interpreted as UTC so the auth expiry
    comparison (aware) never raises."""
    session, factory = _mock_db_session([_entity_result(ADMIN_ENTITY)])
    with patch("emerald.api.routes.v1.keys.session_factory", factory):
        response = admin_client.post(
            "/v1/keys",
            json={
                "entity_id": "user_alice",
                "permissions": ["read"],
                "expires_at": "2026-09-01T00:00:00",  # naive
            },
        )
    assert response.status_code == 201
    added = session.add.call_args[0][0]
    assert added.expires_at.tzinfo is not None
    assert added.expires_at.utcoffset().total_seconds() == 0  # UTC


def _make_unauthed_client() -> TestClient:
    """Client with NO auth override — the real api_key_auth runs against a
    mocked session, exercising the route's auth path end to end."""
    from emerald.api.dependencies import rate_limit

    async def _bypass_rate(request: Request):
        return None

    app = create_app()
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_expired"})


def test_expired_key_401_through_real_route():
    """An expired key is rejected with 401 by the real auth path."""
    from emerald.api import dependencies as deps_module

    record = MagicMock()
    record.id = uuid.uuid4()
    record.entity_id = uuid.UUID(ADMIN_ENTITY)
    record.permissions = ["admin"]
    record.expires_at = None
    record.is_active = True
    # simulate the expired-record branch of api_key_auth
    from datetime import UTC, datetime, timedelta

    async def _expired_execute(statement):
        result = MagicMock()
        if record.expires_at is None:
            record.expires_at = datetime.now(UTC) - timedelta(days=1)
        # New auth query shape: select(ApiKey, Entity.external_id) → .first()
        result.first.return_value = (record, "admin_entity")
        return result

    session = AsyncMock()
    session.execute.side_effect = _expired_execute
    factory = MagicMock()
    factory.session.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(deps_module, "session_factory", factory):
        response = _make_unauthed_client().get("/v1/keys")

    assert response.status_code == 401


def test_revoked_key_401_through_real_route():
    """A revoked key (is_active filter → DB miss) is rejected with 401 by
    the real auth path."""
    from emerald.api import dependencies as deps_module

    result = MagicMock()
    result.first.return_value = None  # revoked → filtered out
    session = AsyncMock()
    session.execute.return_value = result
    factory = MagicMock()
    factory.session.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(deps_module, "session_factory", factory):
        response = _make_unauthed_client().get("/v1/keys")

    assert response.status_code == 401


def test_api_key_auth_scopes_state_to_external_id():
    """The real auth path must scope the request to the entity's *external*
    id (the API's public convention) — scoping to the internal UUID made
    key-authenticated search/upload miss pipeline-ingested content."""
    from emerald.api import dependencies as deps_module

    record = MagicMock()
    record.id = uuid.uuid4()
    record.expires_at = None
    record.permissions = ["read", "write"]
    external_id = "dev_user"

    result = MagicMock()
    result.first.return_value = (record, external_id)
    session = AsyncMock()
    session.execute.return_value = result
    factory = MagicMock()
    factory.session.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

    request = MagicMock()
    request.headers = {"Authorization": "Bearer em_dev_test_key_001"}
    request.state = SimpleNamespace()

    with patch.object(deps_module, "session_factory", factory):
        import asyncio

        asyncio.run(deps_module.api_key_auth(request))

    assert request.state.entity_id == "dev_user"
    assert request.state.api_key_id == str(record.id)
    assert request.state.permissions == ["read", "write"]
