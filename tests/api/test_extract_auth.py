"""Regression tests for the unauthenticated SSRF surface on /v1/extract-url.

Security audit finding (2026-08-10, M2 #14): POST /v1/extract-url performed
an outbound HTTP fetch with no authentication and no rate limiting — an
unauthenticated SSRF / resource-abuse surface.  Fixed by attaching
``api_key_auth`` and ``rate_limit`` dependencies.

These tests assert:
1. Without a valid API key the route rejects with 401 **before** any
   outbound fetch happens (httpx is never called).
2. With authentication and mocked httpx the route still works.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit


def _make_client(authed: bool):
    """Build a TestClient with api_key_auth overridden (or 401-ing)."""
    if authed:

        async def _auth(request: Request):
            request.state.entity_id = "user_alice"
            request.state.api_key_id = "key_test"
            request.state.permissions = ["read", "write"]
            return "authenticated"

    else:

        async def _auth(request: Request):
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Missing or invalid API key")

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=None)
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


def test_extract_url_requires_auth(engine):
    """Unauthenticated request → 401, and httpx must never be invoked."""
    client = _make_client(authed=False)
    with patch(
        "emerald.api.routes.v1.extract.httpx.AsyncClient", side_effect=AssertionError("no fetch")
    ):
        resp = client.post("/v1/extract-url", json={"url": "https://example.com/a"})
    assert resp.status_code == 401


def test_extract_url_works_when_authed():
    """Authenticated request performs the fetch and returns extracted meta."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = (
        "<html><head><title>Hello World</title>"
        '<meta property="og:description" content="A test page"/>'
        "</head></html>"
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    client = _make_client(authed=True)
    with patch("emerald.api.routes.v1.extract.httpx.AsyncClient", return_value=mock_client):
        resp = client.post("/v1/extract-url", json={"url": "https://example.com/a"})

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["title"] == "Hello World"
    assert body["description"] == "A test page"
    assert "example.com/a" in body["url"]
    # The fetch was actually performed exactly once.
    mock_client.get.assert_awaited_once()
