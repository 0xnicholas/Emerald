"""SDK negative tests — error handling for bad inputs."""


import httpx
import pytest

from emerald.sdk import EmeraldClient

# ---- API key ----

def test_client_reads_api_key_from_env(monkeypatch):
    """When api_key is not passed, reads from EMERALD_API_KEY env var."""
    monkeypatch.setenv("EMERALD_API_KEY", "em_from_env_abc123")
    client = EmeraldClient()
    assert client.api_key == "em_from_env_abc123"


def test_client_explicit_key_overrides_env(monkeypatch):
    """Explicit api_key takes precedence over env var."""
    monkeypatch.setenv("EMERALD_API_KEY", "em_from_env")
    client = EmeraldClient(api_key="em_explicit")
    assert client.api_key == "em_explicit"


# ---- Base URL ----

def test_client_reads_base_url_from_env(monkeypatch):
    """When base_url is not passed, reads from EMERALD_BASE_URL env var."""
    monkeypatch.setenv("EMERALD_BASE_URL", "https://api.emerald.ai")
    client = EmeraldClient(api_key="em_test")
    assert client.base_url == "https://api.emerald.ai"


def test_client_default_base_url():
    """Default base_url is localhost:8000."""
    # Clear env var
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("EMERALD_BASE_URL", raising=False)
    client = EmeraldClient(api_key="em_test")
    assert client.base_url == "http://localhost:8000"


# ---- Close safety ----

@pytest.mark.asyncio
async def test_client_close_twice_safe():
    """Calling close() twice does not crash."""
    client = EmeraldClient(api_key="em_test")

    # Manually create a mock client
    async with httpx.AsyncClient(base_url="http://test") as ac:
        client._client = ac

    await client.close()
    # Second close should be a no-op (client already None)
    await client.close()
    # No exception raised


@pytest.mark.asyncio
async def test_client_close_before_use_safe():
    """Calling close() on a never-used client does not crash."""
    client = EmeraldClient(api_key="em_test")
    await client.close()
    # Should not raise
