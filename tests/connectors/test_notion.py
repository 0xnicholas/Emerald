"""Notion connector unit tests — mock httpx responses."""

from __future__ import annotations

import inspect

import pytest

from emerald.connectors.base import SyncMode
from emerald.connectors.notion import NotionConnector


@pytest.fixture(autouse=True)
def _clear_config_cache():
    from emerald.config import get_settings
    get_settings.cache_clear()
    yield


# ---- OAuth Tests ----


@pytest.mark.asyncio
async def test_get_auth_url_returns_valid_url(monkeypatch):
    monkeypatch.setenv("NOTION_CLIENT_ID", "test-notion-client-id")
    connector = NotionConnector(entity_id="user_123")
    url, state = await connector.get_auth_url("https://emerald.ai/callback")
    assert "api.notion.com/v1/oauth/authorize" in url
    assert "response_type=code" in url
    assert "owner=user" in url
    assert len(state) == 32


# ---- Rich Text Extraction Tests ----


def _make_rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}, "plain_text": text}]


def test_extract_rich_text_simple():
    result = NotionConnector._extract_rich_text(_make_rich_text("Hello world"))
    assert result == "Hello world"


def test_extract_rich_text_empty():
    assert NotionConnector._extract_rich_text([]) == ""


def test_extract_rich_text_multiple_parts():
    rich = [
        {"type": "text", "text": {"content": "Hello "}, "plain_text": "Hello "},
        {"type": "text", "text": {"content": "world"}, "plain_text": "world"},
    ]
    assert NotionConnector._extract_rich_text(rich) == "Hello world"


# ---- Block Type Handling Tests ----


def test_get_block_text_paragraph():
    block = {"type": "paragraph", "paragraph": {"rich_text": _make_rich_text("A paragraph.")}}
    result = NotionConnector._get_block_text(block)
    assert result == "A paragraph.\n\n"


def test_get_block_text_code():
    block = {
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": _make_rich_text("print('hello')"),
        },
    }
    result = NotionConnector._get_block_text(block)
    assert result == "```python\nprint('hello')\n```\n\n"


def test_get_block_text_heading():
    block = {"type": "heading_1", "heading_1": {"rich_text": _make_rich_text("Title")}}
    result = NotionConnector._get_block_text(block)
    assert "# Title" in result


def test_get_block_text_unsupported_skipped():
    block = {"type": "divider", "divider": {}}
    result = NotionConnector._get_block_text(block)
    assert result == ""


# ---- Status / Revoke Tests ----


@pytest.mark.asyncio
async def test_status_unconnected():
    connector = NotionConnector(entity_id="user_123")
    status = await connector.status()
    assert status.connected is False
    assert status.provider == "notion"


@pytest.mark.asyncio
async def test_sync_unconnected_returns_error():
    connector = NotionConnector(entity_id="user_123")
    with pytest.raises(RuntimeError, match="credentials not available"):
        await connector.sync(SyncMode.INCREMENTAL)


# ---- Incremental Sync Tests ----


def test_connector_accepts_sync_metadata():
    meta = {"last_synced_at": "2026-05-20T00:00:00Z"}
    connector = NotionConnector(entity_id="user_123", sync_metadata=meta)
    assert connector._sync_metadata_in == meta
    assert connector.get_sync_metadata() is None  # Not set until sync runs


def test_connector_sets_sync_metadata_out_after_sync_called():
    connector = NotionConnector(entity_id="user_123")
    connector._sync_metadata_out = {"last_synced_at": "2026-05-27T12:00:00Z"}
    assert connector.get_sync_metadata() is not None
    assert "last_synced_at" in connector.get_sync_metadata()


# ---- OAuth redirect_uri test ----


def test_handle_callback_accepts_redirect_uri():
    sig = inspect.signature(NotionConnector.handle_callback)
    params = list(sig.parameters.keys())
    assert "redirect_uri" in params, "handle_callback should accept redirect_uri"


# ---- encrypt / decrypt ----


def test_encrypt_decrypt_roundtrip():
    from emerald.connectors.base import ConnectorCredentials
    from emerald.connectors.auth import encrypt_credentials, decrypt_credentials

    original = ConnectorCredentials(
        access_token="nt_secret_abc",
        token_type="Bearer",
        scopes=[],
    )
    encrypted = encrypt_credentials(original)
    decrypted = decrypt_credentials(encrypted)
    assert decrypted.access_token == original.access_token
