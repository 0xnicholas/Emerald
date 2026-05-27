"""Gmail connector unit tests — mock httpx responses."""

from __future__ import annotations

import base64
import json

import pytest
import httpx

from emerald.connectors.base import SyncMode, SyncResult
from emerald.connectors.gmail import GmailConnector

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"  # Will match connector constant


@pytest.fixture(autouse=True)
def _clear_config_cache():
    from emerald.config import get_settings
    get_settings.cache_clear()
    yield

# ---- Helpers ----


def _mock_response(status_code=200, json_data=None, text_data=None):
    """Build a mock httpx.Response."""
    request = httpx.Request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        text=text_data,
        request=request,
    )


def _make_gmail_message(msg_id: str, subject: str, body_plain: str | None = None,
                        body_html: str | None = None) -> dict:
    """Build a realistic Gmail API message dict."""
    headers = [
        {"name": "From", "value": "sender@example.com"},
        {"name": "To", "value": "receiver@example.com"},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": "Mon, 26 May 2026 10:00:00 +0000"},
    ]
    payload = {"mimeType": "text/plain", "headers": headers}
    if body_plain:
        payload["body"] = {"data": base64.urlsafe_b64encode(body_plain.encode()).decode()}
    if body_html and not body_plain:
        payload["mimeType"] = "text/html"
        payload["body"] = {"data": base64.urlsafe_b64encode(body_html.encode()).decode()}
    return {"id": msg_id, "threadId": "thread_1", "payload": payload}


# ---- OAuth Tests ----


@pytest.mark.asyncio
async def test_get_auth_url_returns_valid_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    connector = GmailConnector(entity_id="user_123")
    url, state = await connector.get_auth_url("https://emerald.ai/callback")
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "gmail.readonly" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_handle_callback_credentials_none_by_default():
    connector = GmailConnector(entity_id="user_123")
    assert connector.credentials is None


# ---- Sync Metadata Tests ----


def test_connector_accepts_sync_metadata():
    """sync_metadata parameter flows into connector for historyId persistence."""
    meta = {"lastHistoryId": "12345"}
    connector = GmailConnector(entity_id="user_123", sync_metadata=meta)
    assert connector._sync_metadata_in == meta
    assert connector.get_sync_metadata() is None  # Not set until sync runs


def test_gmail_has_get_sync_metadata():
    """Caller uses get_sync_metadata() to read updated historyId after sync."""
    assert hasattr(GmailConnector, "get_sync_metadata")


# ---- Body Extraction Tests ----


@pytest.mark.parametrize("html_input,expected_contains", [
    ("<p>Hello world</p>", "Hello world"),
    ("<br>line1<br>line2", "line1\nline2"),
    ("<b>bold</b> &amp; <i>italic</i>", "bold & italic"),
])
def test_extract_html_to_text(html_input, expected_contains):
    result = GmailConnector._extract_html_to_text(html_input)
    assert expected_contains in result


def test_extract_html_handles_empty():
    assert GmailConnector._extract_html_to_text("") == ""


def test_extract_html_collapses_multiple_newlines():
    result = GmailConnector._extract_html_to_text("<p>a</p><br><br><br><p>b</p>")
    # Should not have 3+ consecutive newlines
    assert "\n\n\n\n" not in result


# ---- Sync Tests ----


@pytest.mark.asyncio
async def test_sync_unconnected_returns_error():
    connector = GmailConnector(entity_id="user_123")
    with pytest.raises(RuntimeError, match="credentials not available"):
        await connector.sync(SyncMode.INCREMENTAL)


# ---- Status / Revoke Tests ----


@pytest.mark.asyncio
async def test_status_unconnected():
    connector = GmailConnector(entity_id="user_123")
    status = await connector.status()
    assert status.connected is False
    assert status.provider == "gmail"


# ---- encrypt / decrypt Tests ----


def test_encrypt_decrypt_roundtrip():
    from emerald.connectors.base import ConnectorCredentials
    from emerald.connectors.auth import encrypt_credentials, decrypt_credentials

    original = ConnectorCredentials(
        access_token="gm_token_abc",
        refresh_token="gm_refresh_xyz",
        token_type="Bearer",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    encrypted = encrypt_credentials(original)
    decrypted = decrypt_credentials(encrypted)
    assert decrypted.access_token == original.access_token
    assert decrypted.refresh_token == original.refresh_token


# ---- Sync tests with mock ----


def _dummy_credentials():
    from emerald.connectors.base import ConnectorCredentials
    return ConnectorCredentials(access_token="test_token")


@pytest.mark.asyncio
async def test_sync_message_skips_empty_body(monkeypatch):
    """Messages with no body data are skipped, not ingested."""
    connector = GmailConnector(entity_id="user_123")
    connector.credentials = _dummy_credentials()

    # Empty payload: no body data
    msg = {"id": "msg_1", "threadId": "t1", "payload": {"mimeType": "text/plain", "headers": []}}

    class _MockResponse:
        status_code = 200
        @staticmethod
        def json():
            return msg
        @staticmethod
        def raise_for_status():
            pass

    async def _mock_get(*args, **kwargs):
        return _MockResponse()

    # Monkey-patch client
    client = httpx.AsyncClient(base_url=GMAIL_API_BASE)
    monkeypatch.setattr(client, "get", _mock_get)
    monkeypatch.setattr(connector, "_get_api_client", lambda: client)

    result = await connector._sync_message(client, "msg_1")
    assert result is False  # skipped
