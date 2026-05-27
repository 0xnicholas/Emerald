"""Gmail connector E2E tests — requires real Google OAuth credentials.

Set GMAIL_TEST_REFRESH_TOKEN to run. Skipped in CI.
"""

import os

import pytest

from emerald.connectors.base import SyncMode
from emerald.connectors.gmail import GmailConnector


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GMAIL_TEST_REFRESH_TOKEN"),
        reason="GMAIL_TEST_REFRESH_TOKEN not set",
    ),
]


@pytest.fixture
async def gmail_connector():
    connector = GmailConnector(entity_id="e2e_test_user")
    return connector


@pytest.mark.asyncio
async def test_oauth_url_generation(monkeypatch, gmail_connector):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "e2e-test-client-id")
    url, state = await gmail_connector.get_auth_url(
        "http://localhost:8000/v1/connectors/gmail/callback"
    )
    assert "accounts.google.com" in url
    assert len(state) == 32


@pytest.mark.asyncio
async def test_sync_requires_credentials(gmail_connector):
    with pytest.raises(RuntimeError, match="credentials not available"):
        await gmail_connector.sync(SyncMode.FULL)
