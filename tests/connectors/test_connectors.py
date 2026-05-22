"""Connector integration tests — OAuth flow, sync, webhook, pipeline integration."""

import uuid
from datetime import datetime, timezone

import pytest

from emerald.connectors.base import (
    BaseConnector,
    ConnectorCredentials,
    ConnectorStatus,
    SyncMode,
    SyncResult,
)
from emerald.connectors.auth import encrypt_credentials, decrypt_credentials
from emerald.connectors.registry import ConnectorRegistry
from emerald.core.engine import MemoryEngine
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.core.extractor import ExtractorRegistry
from emerald.core.chunker import ChunkerRegistry
from emerald.pipeline.extraction.text import TextExtractor
from emerald.pipeline.chunking.text import TextChunker


# ---- Mock Connector for testing ----

class MockConnector(BaseConnector):
    """Simulates an external service connector for testing."""

    provider = "mock_service"
    _files = {
        "file_1": b"Mock file content: Python best practices guide",
        "file_2": b"Mock file content: TypeScript handbook chapter 1",
        "file_3": b"Mock file content: Deployment walkthrough for Kubernetes",
    }

    def __init__(self, entity_id: str):
        self.entity_id = entity_id
        self.credentials = None
        self._connected = False

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        state = uuid.uuid4().hex
        return f"https://mock.service/oauth?state={state}", state

    async def handle_callback(self, code: str, state: str) -> ConnectorCredentials:
        self._connected = True
        return ConnectorCredentials(
            access_token="mock_access_token_" + uuid.uuid4().hex,
            refresh_token="mock_refresh_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc),
            scopes=["read", "write"],
        )

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        if not self._connected:
            return SyncResult(provider=self.provider, errors=["Not connected"])

        synced = 0
        for file_id, content in self._files.items():
            synced += 1
            # In production, this submits to the Emerald pipeline
        return SyncResult(
            provider=self.provider,
            files_synced=synced,
            duration_seconds=0.05,
        )

    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        event = payload.get("event", "unknown")
        if event in ("file.created", "file.updated"):
            return True
        return False

    async def revoke(self) -> None:
        self._connected = False
        self.credentials = None

    async def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            provider=self.provider,
            connected=self._connected,
            sync_status="active" if self._connected else "inactive",
        )


# ---- Fixtures ----

@pytest.fixture
def connector():
    return MockConnector(entity_id="user_123")


@pytest.fixture
def engine():
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    embedder = MockEmbeddingProvider(dimension=128)
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)

    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=graph,
        vector=vector,
        use_db=False,
    )


@pytest.fixture
def registry():
    reg = ConnectorRegistry()
    reg.register("mock_service", MockConnector)
    return reg


# ---- OAuth flow tests ----


@pytest.mark.asyncio
async def test_get_auth_url_returns_url_and_state(connector):
    """OAuth flow starts with auth URL and state token."""
    url, state = await connector.get_auth_url("https://emerald.ai/callback")
    assert "mock.service" in url
    assert len(state) == 32  # UUID hex


@pytest.mark.asyncio
async def test_handle_callback_returns_credentials(connector):
    """OAuth callback exchanges code for credentials."""
    creds = await connector.handle_callback("auth_code_123", "state_456")
    assert creds.access_token.startswith("mock_access_token_")
    assert creds.token_type == "Bearer"
    assert "read" in creds.scopes


@pytest.mark.asyncio
async def test_full_auth_flow(connector):
    """Complete OAuth flow: get URL → callback → connected."""
    url, state = await connector.get_auth_url("https://callback.example.com")
    creds = await connector.handle_callback("code", state)
    connector.credentials = creds

    status = await connector.status()
    assert status.connected is True
    assert status.sync_status == "active"


# ---- Sync tests ----


@pytest.mark.asyncio
async def test_sync_unconnected_returns_error(connector):
    """Sync before auth returns error."""
    result = await connector.sync(SyncMode.INCREMENTAL)
    assert result.files_synced == 0
    assert len(result.errors) > 0


@pytest.mark.asyncio
async def test_sync_connected_returns_files(connector):
    """Sync after auth returns synced files."""
    await connector.handle_callback("code", "state")
    result = await connector.sync(SyncMode.FULL)
    assert result.files_synced == 3  # MockConnector has 3 files


@pytest.mark.asyncio
async def test_sync_incremental_mode(connector):
    """Incremental sync mode is supported."""
    await connector.handle_callback("code", "state")
    result = await connector.sync(SyncMode.INCREMENTAL)
    assert result.files_synced == 3
    assert result.duration_seconds > 0


# ---- Webhook tests ----


@pytest.mark.asyncio
async def test_webhook_file_created_triggers_sync(connector):
    """Webhook for file creation triggers sync."""
    triggered = await connector.handle_webhook(
        {"event": "file.created", "file_id": "new_file"},
        "valid_signature",
    )
    assert triggered is True


@pytest.mark.asyncio
async def test_webhook_unknown_event_no_trigger(connector):
    """Unknown webhook events don't trigger sync."""
    triggered = await connector.handle_webhook(
        {"event": "comment.added"},
        "valid_signature",
    )
    assert triggered is False


# ---- Revoke tests ----


@pytest.mark.asyncio
async def test_revoke_disconnects(connector):
    """Revoking OAuth clears credentials and disconnects."""
    await connector.handle_callback("code", "state")
    await connector.revoke()

    status = await connector.status()
    assert status.connected is False
    assert connector.credentials is None


# ---- Credential encryption tests ----


def test_encrypt_decrypt_roundtrip():
    """AES-256-GCM encryption roundtrip preserves credentials."""
    original = ConnectorCredentials(
        access_token="secret_token_abc123",
        refresh_token="refresh_xyz",
        token_type="Bearer",
        scopes=["read", "write"],
    )

    encrypted = encrypt_credentials(original)
    assert isinstance(encrypted, bytes)
    assert len(encrypted) > 12  # At least nonce + ciphertext

    decrypted = decrypt_credentials(encrypted)
    assert decrypted.access_token == original.access_token
    assert decrypted.refresh_token == original.refresh_token
    assert decrypted.scopes == original.scopes


# ---- Registry tests ----


def test_registry_get_registered(registry):
    """Can retrieve a registered connector class."""
    cls = registry.get("mock_service")
    assert cls is MockConnector


def test_registry_unknown_raises(registry):
    """Getting an unregistered provider raises error."""
    from emerald.connectors.registry import UnsupportedConnectorError

    with pytest.raises(UnsupportedConnectorError):
        registry.get("unknown_service")


def test_registry_list_providers(registry):
    """Can list all registered providers."""
    providers = registry.list_providers()
    assert "mock_service" in providers


# ---- Pipeline integration ----


@pytest.mark.asyncio
async def test_synced_content_enters_pipeline(engine, connector):
    """Files synced from a connector can be ingested into Emerald."""
    await connector.handle_callback("code", "state")
    result = await connector.sync(SyncMode.FULL)

    assert result.files_synced > 0

    # Simulate: for each synced file, add to engine
    for file_id, content in connector._files.items():
        text = content.decode("utf-8")
        add_result = await engine.add(
            text, entity_id=connector.entity_id, content_type="text",
        )
        assert len(add_result.memory_ids) > 0

    # All synced files should be searchable
    profile = await engine.graph.list_latest_memories(connector.entity_id)
    assert len(profile) >= 3
