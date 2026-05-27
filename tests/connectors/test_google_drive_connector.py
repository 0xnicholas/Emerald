"""Tests for Google Drive connector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.connectors.google_drive import GoogleDriveConnector


@pytest.fixture
def connector():
    return GoogleDriveConnector(entity_id="user_123")


# ---- OAuth ----

@pytest.mark.asyncio
async def test_get_auth_url_requires_client_id(connector):
    with pytest.raises(RuntimeError):
        await connector.get_auth_url("http://localhost/callback")


@pytest.mark.asyncio
async def test_get_auth_url_returns_url_and_state(connector, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_google_id")
    from emerald.config import get_settings
    get_settings.cache_clear()

    url, state = await connector.get_auth_url("http://localhost/callback")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test_google_id" in url
    assert "scope=" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_handle_callback_exchanges_code(connector, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test_secret")
    from emerald.config import get_settings
    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "ya_testtoken",
        "refresh_token": "refresh_123",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/drive.readonly",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        creds = await connector.handle_callback("test_code", "test_state")

    assert creds.access_token == "ya_testtoken"
    assert creds.refresh_token == "refresh_123"
    assert "drive.readonly" in creds.scopes[0]


# ---- Sync ----

@pytest.mark.asyncio
async def test_sync_requires_credentials(connector):
    with pytest.raises(RuntimeError, match="credentials not available"):
        await connector.sync()


# ---- Webhook ----

@pytest.mark.asyncio
async def test_handle_webhook_triggers_sync(connector):
    payload = {"resourceId": "res_123", "channelId": "chan_456"}
    result = await connector.handle_webhook(payload, "")
    assert result is True


# ---- Lifecycle ----

@pytest.mark.asyncio
async def test_status_disconnected(connector):
    status = await connector.status()
    assert status.provider == "google_drive"
    assert status.connected is False


@pytest.mark.asyncio
async def test_status_connected(connector):
    from emerald.connectors.base import ConnectorCredentials
    connector.credentials = ConnectorCredentials(access_token="test")
    status = await connector.status()
    assert status.connected is True


# ---- Helpers ----

def test_detect_content_type(connector):
    assert connector._detect_content_type("report.pdf", "application/pdf") == "pdf"
    assert connector._detect_content_type("image.png", "image/png") == "image"
    assert connector._detect_content_type("notes.md", "text/plain") == "markdown"
    assert connector._detect_content_type("data.json", "application/json") == "text"
    assert connector._detect_content_type("readme.txt", "text/plain") == "text"


# ---- Encryption roundtrip ----

@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip(connector, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "b" * 64)
    from emerald.config import get_settings
    get_settings.cache_clear()

    from emerald.connectors.base import ConnectorCredentials
    connector.credentials = ConnectorCredentials(
        access_token="secret_token",
        refresh_token="refresh_secret",
        scopes=["drive.readonly"],
    )

    encrypted = connector.encrypt()
    assert encrypted is not None

    restored = GoogleDriveConnector.decrypt(encrypted, entity_id="user_123")
    assert restored.credentials.access_token == "secret_token"
    assert restored.credentials.refresh_token == "refresh_secret"
