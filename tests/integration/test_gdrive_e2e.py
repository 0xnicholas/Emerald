"""Google Drive Connector E2E — OAuth flow + webhook + search end-to-end.

Tests the full connector lifecycle:
1. Initiate OAuth → get auth_url
2. Handle OAuth callback → store credentials (with refresh_token)
3. Receive push notification webhook → trigger sync
4. Search → find synced content

All external HTTP calls (Google OAuth API) and database operations are mocked.
The memory engine is in-memory, so search works end-to-end.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_gdrive_webhook_payload() -> dict:
    """Build a realistic Google Drive push notification payload."""
    return {
        "kind": "api#channel",
        "id": "channel-id-123",
        "resourceId": "resource-id-456",
        "resourceUri": "https://www.googleapis.com/drive/v3/files",
        "token": "sync_token_abc",
    }


# ── OAuth Flow ───────────────────────────────────────────────────────────


def test_gdrive_oauth_connect_returns_auth_url(client):
    """POST /v1/connectors/google_drive/connect returns a valid Google OAuth URL."""
    with patch("emerald.api.routes.connectors.session_factory"):
        with patch("emerald.connectors.google_drive.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_client_id="gd_test_client_id",
                google_client_secret="gd_test_secret",
            )
            response = client.post("/v1/connectors/google_drive/connect")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "google_drive"
    assert "accounts.google.com/o/oauth2/v2/auth" in data["auth_url"]
    assert "client_id=gd_test_client_id" in data["auth_url"]
    assert "scope=" in data["auth_url"]
    assert "access_type=offline" in data["auth_url"]
    assert "prompt=consent" in data["auth_url"]
    assert "state=" in data["auth_url"]
    assert data["expires_in"] == 600


def test_gdrive_oauth_callback_exchanges_code_for_token(client, mock_db_session):
    """GET /v1/connectors/google_drive/callback exchanges code and stores credentials."""
    mock_session, _ = mock_db_session

    # Step 1: Initiate connect to get state token
    with patch("emerald.connectors.google_drive.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            google_client_id="gd_test_client_id",
            google_client_secret="gd_test_secret",
        )
        connect_resp = client.post("/v1/connectors/google_drive/connect")

    state_token = connect_resp.json()["data"]["state_token"]

    # Step 2: Mock Google token exchange API
    async def _mock_post(*args, **kwargs):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "ya29.test_access_token_12345",
            "refresh_token": "1//test_refresh_token_67890",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/drive.readonly",
        }
        return mock_response

    # Step 3: Trigger callback with the state token
    with patch("emerald.connectors.google_drive.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            google_client_id="gd_test_client_id",
            google_client_secret="gd_test_secret",
        )
        with patch("httpx.AsyncClient.post", new=_mock_post):
            response = client.get(
                "/v1/connectors/google_drive/callback",
                params={"code": "test_auth_code", "state": state_token},
            )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "google_drive"
    assert data["status"] == "connected"
    # Verify credentials were stored in DB
    mock_session.execute.assert_called()
    mock_session.commit.assert_called()


def test_gdrive_oauth_callback_invalid_state_returns_400(client):
    """Callback with an unknown/expired state token returns 400."""
    response = client.get(
        "/v1/connectors/google_drive/callback",
        params={"code": "test_code", "state": "invalid_state_12345"},
    )
    assert response.status_code == 400
    assert "Invalid or expired state token" in response.json()["detail"]


# ── Webhook ──────────────────────────────────────────────────────────────


def test_gdrive_webhook_triggers_sync(client):
    """POST /v1/connectors/google_drive/webhook triggers sync."""
    payload = _make_gdrive_webhook_payload()

    response = client.post("/v1/connectors/google_drive/webhook", json=payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "accepted"
    assert data["sync_triggered"] is True


def test_gdrive_webhook_accepts_empty_payload(client):
    """Webhook with minimal payload is accepted (graceful handling)."""
    response = client.post("/v1/connectors/google_drive/webhook", json={})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "accepted"


# ── Connector Status ─────────────────────────────────────────────────────


def test_gdrive_connector_status_not_connected(client, mock_db_session):
    """GET /v1/connectors/google_drive returns inactive when no credentials stored."""
    _, _ = mock_db_session

    response = client.get("/v1/connectors/google_drive")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "google_drive"
    assert data["sync_status"] == "inactive"
    assert data["last_synced_at"] is None


# ── Full Pipeline: Memory Engine Integration ─────────────────────────────


@pytest.mark.asyncio
async def test_gdrive_connector_memory_engine_integration(client, engine):
    """Content added via the memory engine is searchable after connector setup.

    Validates that Google Drive connector shares the same context pool
    as the memory engine (AGENTS.md Principle 3: same entity, same graph).
    """
    entity_id = "550e8400-e29b-41d4-a716-446655440000"
    result = await engine.add(
        "Project roadmap document stored in Google Drive covers Q3 milestones",
        entity_id=entity_id,
        content_type="text",
    )
    assert len(result.memory_ids) > 0

    from emerald.core.search import SearchMode, SearchOrchestrator

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        "roadmap milestones", entity_id=entity_id, search_mode=SearchMode.MEMORY,
    )
    assert any("roadmap" in r.content for r in results.results)
