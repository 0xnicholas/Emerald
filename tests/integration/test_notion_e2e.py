"""Notion connector E2E tests — requires real Notion OAuth credentials.

Set NOTION_TEST_ACCESS_TOKEN to run. Skipped in CI.
"""

import os

import pytest

from emerald.connectors.base import SyncMode
from emerald.connectors.notion import NotionConnector


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("NOTION_TEST_ACCESS_TOKEN"),
        reason="NOTION_TEST_ACCESS_TOKEN not set",
    ),
]


@pytest.fixture
async def notion_connector():
    connector = NotionConnector(entity_id="e2e_test_user")
    from emerald.connectors.base import ConnectorCredentials
    connector.credentials = ConnectorCredentials(
        access_token=os.environ["NOTION_TEST_ACCESS_TOKEN"],
        token_type="Bearer",
    )
    return connector


@pytest.mark.asyncio
async def test_oauth_url_generation(monkeypatch, notion_connector):
    monkeypatch.setenv("NOTION_CLIENT_ID", "e2e-test-notion-client-id")
    url, state = await notion_connector.get_auth_url(
        "http://localhost:8000/v1/connectors/notion/callback"
    )
    assert "api.notion.com" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_sync_requires_credentials():
    connector = NotionConnector(entity_id="e2e_test_user")
    with pytest.raises(RuntimeError, match="credentials not available"):
        await connector.sync(SyncMode.FULL)
