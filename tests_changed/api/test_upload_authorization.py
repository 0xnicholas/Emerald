"""Regression tests for the upload entity-authorization gap (P0 security fix).

P0 issue: `POST /v1/upload` did not call
`_authorize_entity(request, entity_id)`, allowing any authenticated API key
with `write` permission to upload files into ANY entity namespace.

These tests directly assert that the upload route enforces the
entity-authorization check by patching the helper and calling the function.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission


def _make_authed_client(engine, scoped_entity: str):
    """Build a TestClient whose api_key_auth sets request.state.entity_id."""
    async def _auth(request: Request):
        request.state.entity_id = scoped_entity
        request.state.api_key_id = "key_test"
        request.state.permissions = ["read", "write"]
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=engine)
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


def test_upload_route_calls_authorize_entity_v1(engine):
    """POST /v1/upload must invoke _authorize_entity with the request's entity_id.

    This is the direct regression test for the cross-entity pollution
    vulnerability: a write-permission key must never be able to push files
    into another entity's namespace.
    """
    from fastapi import HTTPException
    client = _make_authed_client(engine, "user_alice")
    from emerald.api.routes.v1 import upload as v1_upload

    # Patch the helper to short-circuit with 403. This both verifies the
    # call happens and prevents the route from reaching any real I/O
    # (MinIO, Postgres, pipeline orchestrator).
    def _raise_403(request, entity_id):
        raise HTTPException(status_code=403, detail="Entity not authorized")

    with patch.object(v1_upload, "_authorize_entity", side_effect=_raise_403) as auth_spy, \
         patch.object(v1_upload, "_get_minio_client") as minio_spy:
        minio_spy.return_value = MagicMock()

        files = {"file": ("hello.txt", io.BytesIO(b"hello"), "text/plain")}
        data = {"entity_id": "user_bob"}
        response = client.post("/v1/upload", files=files, data=data)

    # The auth helper must have been invoked.
    assert auth_spy.called, (
        "POST /v1/upload did not call _authorize_entity — cross-entity "
        "uploads are possible. This is the P0 security regression."
    )
    # And it must have been called with the entity_id from the form body.
    args, kwargs = auth_spy.call_args
    # Signature: _authorize_entity(request: Request, entity_id: str)
    assert kwargs.get("entity_id") == "user_bob" or (
        len(args) >= 2 and args[1] == "user_bob"
    ), f"_authorize_entity called with wrong entity_id: args={args} kwargs={kwargs}"
    # Short-circuit must yield 403.
    assert response.status_code == 403, (
        f"Expected 403 from authorization short-circuit, got {response.status_code}"
    )


def test_upload_authorize_entity_raises_403_on_mismatch(engine):
    """When _authorize_entity raises HTTPException(403), upload returns 403.

    This proves the auth check is integrated into the request flow, not
    just defined but never reached.
    """
    from fastapi import HTTPException

    from emerald.api.routes.v1 import upload as v1_upload

    client = _make_authed_client(engine, "user_alice")

    def _raise_403(request, entity_id):
        raise HTTPException(status_code=403, detail="Entity not authorized")

    with patch.object(v1_upload, "_authorize_entity", side_effect=_raise_403), \
         patch.object(v1_upload, "_get_minio_client") as minio_spy:
        minio_spy.return_value = MagicMock()

        files = {"file": ("hello.txt", io.BytesIO(b"hello"), "text/plain")}
        data = {"entity_id": "user_bob"}
        response = client.post("/v1/upload", files=files, data=data)

    assert response.status_code == 403, (
        f"Expected 403 when _authorize_entity raises, got {response.status_code}: {response.text}"
    )
    # MinIO must NOT have been reached.
    minio_client = minio_spy.return_value
    assert not minio_client.put_object.called, (
        "MinIO was called despite authorization failure"
    )


# ---------- End-to-end: real authorize_entity (no patches) ----------
#
# The tests above patch _authorize_entity, which means a regression that
# REMOVED the call entirely would still pass (because the patch would just
# be unused).  This test uses the real authorize_entity helper so a
# regression that drops the call would fail with 200 + MinIO called,
# catching the actual security gap.

def test_upload_end_to_end_rejects_mismatched_entity(engine):
    """Real authorize_entity must run and reject cross-entity uploads.

    If the route forgets to call _authorize_entity, the request would
    reach MinIO (or the DB) and return 202.  We assert 403 to lock the
    contract.
    """
    # Patches below are only for IO-bound side effects (MinIO, DB lookup).
    # We do NOT patch _authorize_entity — it must run for real.
    from emerald.api.routes.v1 import upload as v1_upload

    client = _make_authed_client(engine, "user_alice")  # API key scoped to alice
    with patch.object(v1_upload, "_get_minio_client") as minio_spy, \
         patch("emerald.db.session.session_factory") as sf_spy:
        minio_spy.return_value = MagicMock()

        # The DB lookup resolves any entity.  We patch it to return a
        # fake entity for "user_bob" so the route doesn't 404 before
        # reaching the auth check.
        fake_entity = MagicMock()
        fake_entity.id = "fake-uuid"
        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = fake_entity
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_session.add = MagicMock()
        fake_session.commit = AsyncMock()
        fake_session.refresh = AsyncMock()
        sf_spy.session.return_value.__aenter__ = AsyncMock(return_value=fake_session)
        sf_spy.session.return_value.__aexit__ = AsyncMock(return_value=False)

        files = {"file": ("hello.txt", io.BytesIO(b"hello"), "text/plain")}
        data = {"entity_id": "user_bob"}
        response = client.post("/v1/upload", files=files, data=data)

    assert response.status_code == 403, (
        f"Cross-entity upload must be 403, got {response.status_code}: {response.text}. "
        f"If this fails, the route may have removed the _authorize_entity call."
    )
    minio_client = minio_spy.return_value
    assert not minio_client.put_object.called, (
        "MinIO was called for cross-entity upload — auth check was bypassed."
    )
