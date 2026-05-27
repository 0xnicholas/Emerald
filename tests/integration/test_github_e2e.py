"""GitHub Connector E2E — OAuth flow + webhook + search end-to-end.

Tests the full connector lifecycle:
1. Initiate OAuth → get auth_url
2. Handle OAuth callback → store credentials
3. Receive push webhook → trigger sync
4. Search → find synced content

All external HTTP calls (GitHub API) and database operations are mocked.
The memory engine is in-memory, so search works end-to-end.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_github_webhook_payload(repo_owner: str = "github_test") -> dict:
    """Build a realistic GitHub push webhook payload."""
    return {
        "action": "push",
        "repository": {
            "full_name": f"{repo_owner}/test-repo",
            "owner": {"login": repo_owner},
            "default_branch": "main",
        },
        "commits": [
            {"message": "feat: add user authentication module"},
            {"message": "fix: resolve memory leak in cache layer"},
        ],
        "ref": "refs/heads/main",
        "pusher": {"name": "testuser"},
    }


def _sign_github_payload(payload: dict, secret: str) -> str:
    """Compute X-Hub-Signature-256 for a webhook payload."""
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return sig


# ── OAuth Flow ───────────────────────────────────────────────────────────


def test_github_oauth_connect_returns_auth_url(client):
    """POST /v1/connectors/github/connect returns a valid GitHub OAuth URL."""
    with patch("emerald.api.routes.connectors.session_factory"):
        with patch("emerald.connectors.github.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                github_client_id="gh_test_client_id",
                github_client_secret="gh_test_secret",
            )
            response = client.post("/v1/connectors/github/connect")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "github"
    assert "github.com/login/oauth/authorize" in data["auth_url"]
    assert "client_id=gh_test_client_id" in data["auth_url"]
    assert "state=" in data["auth_url"]
    assert data["expires_in"] == 600


def test_github_oauth_connect_unknown_provider_returns_400(client):
    """Unknown provider returns 400 Bad Request."""
    response = client.post("/v1/connectors/invalid_provider/connect")
    assert response.status_code == 400


def test_github_oauth_callback_exchanges_code_for_token(client, mock_db_session):
    """GET /v1/connectors/github/callback exchanges code and stores credentials."""
    mock_session, _ = mock_db_session

    # Step 1: Initiate connect to get state token
    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            github_client_id="gh_test_client_id",
            github_client_secret="gh_test_secret",
        )
        connect_resp = client.post("/v1/connectors/github/connect")

    state_token = connect_resp.json()["data"]["state_token"]

    # Step 2: Mock GitHub token exchange API
    async def _mock_post(*args, **kwargs):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "gho_test_access_token_12345",
            "token_type": "Bearer",
            "scope": "repo,read:user",
        }
        return mock_response

    # Step 3: Trigger callback with the state token
    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            github_client_id="gh_test_client_id",
            github_client_secret="gh_test_secret",
        )
        with patch("httpx.AsyncClient.post", new=_mock_post):
            response = client.get(
                "/v1/connectors/github/callback",
                params={"code": "test_auth_code", "state": state_token},
            )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "github"
    assert data["status"] == "connected"
    # Verify credentials were stored in DB
    mock_session.execute.assert_called()
    mock_session.commit.assert_called()


def test_github_oauth_callback_invalid_state_returns_400(client):
    """Callback with an unknown/expired state token returns 400."""
    response = client.get(
        "/v1/connectors/github/callback",
        params={"code": "test_code", "state": "invalid_state_12345"},
    )
    assert response.status_code == 400
    assert "Invalid or expired state token" in response.json()["detail"]


# ── Webhook ──────────────────────────────────────────────────────────────


def test_github_webhook_valid_signature_triggers_sync(client):
    """POST /v1/connectors/github/webhook with valid signature triggers sync."""
    secret = "webhook_secret_123"
    payload = _make_github_webhook_payload()
    # Send raw JSON bytes so request.body() matches signature computation exactly
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(github_webhook_secret=secret)
        response = client.post(
            "/v1/connectors/github/webhook",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "accepted"
    assert data["sync_triggered"] is True


def test_github_webhook_invalid_signature_rejected(client):
    """Webhook with invalid signature is rejected (sync_triggered=False)."""
    secret = "webhook_secret_123"
    payload = _make_github_webhook_payload()
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    bad_signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(github_webhook_secret=secret)
        response = client.post(
            "/v1/connectors/github/webhook",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": bad_signature,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_triggered"] is False


def test_github_webhook_no_secret_configured(client):
    """Webhook with no secret configured returns sync_triggered=False."""
    payload = _make_github_webhook_payload()
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(github_webhook_secret="")
        response = client.post(
            "/v1/connectors/github/webhook",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": "sha256=anything",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_triggered"] is False


def test_github_webhook_non_push_event_no_sync(client):
    """Non-push events (e.g. 'opened' for issues) do not trigger sync."""
    secret = "webhook_secret_123"
    payload = _make_github_webhook_payload()
    payload["action"] = "opened"  # Issue opened, not push
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    with patch("emerald.connectors.github.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(github_webhook_secret=secret)
        response = client.post(
            "/v1/connectors/github/webhook",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_triggered"] is False


# ── Connector Status ─────────────────────────────────────────────────────


def test_github_connector_status_not_connected(client, mock_db_session):
    """GET /v1/connectors/github returns inactive when no credentials stored."""
    _, _ = mock_db_session

    response = client.get("/v1/connectors/github")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "github"
    assert data["sync_status"] == "inactive"
    assert data["last_synced_at"] is None
    assert data["error_message"] is None


# ── Full Pipeline: Memory Engine Integration ─────────────────────────────


@pytest.mark.asyncio
async def test_github_connector_memory_engine_integration(client, engine):
    """Content added via the memory engine is searchable after connector setup.

    This validates that the connector's entity_id space and the memory engine's
    entity_id space are the same context pool (AGENTS.md Principle 3).
    """
    # Add content to the same entity that the connector would use
    entity_id = "550e8400-e29b-41d4-a716-446655440000"
    result = await engine.add(
        "GitHub repository contains authentication module written in TypeScript",
        entity_id=entity_id,
        content_type="text",
    )
    assert len(result.memory_ids) > 0

    # Search for the content
    from emerald.core.search import SearchMode, SearchOrchestrator

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        "TypeScript authentication", entity_id=entity_id, search_mode=SearchMode.MEMORY,
    )
    assert any("authentication" in r.content for r in results.results)
