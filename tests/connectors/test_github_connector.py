"""Tests for GitHub connector."""

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.connectors.github import GitHubConnector


@pytest.fixture
def connector():
    return GitHubConnector(entity_id="user_123")


# ---- OAuth ----

@pytest.mark.asyncio
async def test_get_auth_url_requires_client_id(connector):
    with pytest.raises(RuntimeError):
        await connector.get_auth_url("http://localhost/callback")


@pytest.mark.asyncio
async def test_get_auth_url_returns_url_and_state(connector, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test_client_id")
    # Reload settings cache
    from emerald.config import get_settings
    get_settings.cache_clear()

    url, state = await connector.get_auth_url("http://localhost/callback")
    assert url.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=test_client_id" in url
    assert "state=" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_handle_callback_exchanges_code(connector, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test_id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test_secret")
    from emerald.config import get_settings
    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "gho_testtoken",
        "token_type": "bearer",
        "scope": "repo,read:user",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        creds = await connector.handle_callback("test_code", "test_state")

    assert creds.access_token == "gho_testtoken"
    assert "repo" in creds.scopes


# ---- Webhook ----

@pytest.mark.asyncio
async def test_handle_webhook_validates_signature(connector, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "mysecret")
    from emerald.config import get_settings
    get_settings.cache_clear()

    payload = {"action": "push", "repository": {"full_name": "test/repo"}}
    raw_body = b'{"action":"push"}'
    payload["_raw_body"] = raw_body

    signature = "sha256=" + hmac.new(
        b"mysecret", raw_body, hashlib.sha256
    ).hexdigest()

    result = await connector.handle_webhook(payload, signature)
    assert result is True  # push event triggers sync


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_signature(connector, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "mysecret")
    from emerald.config import get_settings
    get_settings.cache_clear()

    payload = {"action": "push", "repository": {"full_name": "test/repo"}}
    payload["_raw_body"] = b'{"action":"push"}'

    result = await connector.handle_webhook(payload, "sha256=invalid")
    assert result is False


# ---- Sync helpers ----

@pytest.mark.asyncio
async def test_sync_requires_credentials(connector):
    with pytest.raises(RuntimeError, match="credentials not available"):
        await connector.sync()


# ---- Lifecycle ----

@pytest.mark.asyncio
async def test_status_disconnected(connector):
    status = await connector.status()
    assert status.provider == "github"
    assert status.connected is False
    assert status.sync_status == "inactive"


@pytest.mark.asyncio
async def test_status_connected(connector):
    from emerald.connectors.base import ConnectorCredentials
    connector.credentials = ConnectorCredentials(access_token="test")
    status = await connector.status()
    assert status.connected is True
    assert status.sync_status == "active"


# ---- Encryption roundtrip ----

@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip(connector, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "a" * 64)
    from emerald.config import get_settings
    get_settings.cache_clear()

    from emerald.connectors.base import ConnectorCredentials
    connector.credentials = ConnectorCredentials(
        access_token="secret_token",
        scopes=["repo"],
    )

    encrypted = connector.encrypt()
    assert encrypted is not None

    restored = GitHubConnector.decrypt(encrypted, entity_id="user_123")
    assert restored.credentials.access_token == "secret_token"
    assert restored.credentials.scopes == ["repo"]
