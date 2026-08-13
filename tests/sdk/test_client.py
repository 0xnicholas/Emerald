"""Tests for Python SDK client."""

import httpx
import pytest

from emerald.api.app import create_app
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor
from emerald.sdk import EmeraldClient
from emerald.sdk.models import AddResult, Profile, SearchResults


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
async def client(engine):
    """SDK client wired to in-memory FastAPI app."""
    from fastapi import Request

    from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission

    async def _bypass_auth(request: Request):
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=engine)
    app.dependency_overrides[api_key_auth] = _bypass_auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        c = EmeraldClient(
            api_key="em_test123",
            base_url="http://test",
        )
        c._client = ac  # Inject the test client
        yield c


# ---- SDK method signatures ----

@pytest.mark.asyncio
async def test_client_has_four_core_methods(client):
    """SDK exposes exactly 4 core methods: add, search, profile, upload."""
    assert hasattr(client, "add")
    assert hasattr(client, "search")
    assert hasattr(client, "profile")
    assert hasattr(client, "upload")
    assert callable(client.add)
    assert callable(client.search)
    assert callable(client.profile)
    assert callable(client.upload)


# ---- add() ----

@pytest.mark.asyncio
async def test_add_returns_add_result(client):
    """add() returns an AddResult with memory IDs."""
    result = await client.add("用户喜欢 TypeScript", entity_id="user_123")
    assert isinstance(result, AddResult)
    assert len(result.memory_ids) > 0
    assert result.pipeline_status == "done"


@pytest.mark.asyncio
async def test_add_with_metadata(client):
    """add() accepts optional title and metadata."""
    result = await client.add(
        "用户的编程偏好",
        entity_id="user_123",
        title="编程偏好",
        metadata={"source": "chat", "session_id": "sess_456"},
    )
    assert len(result.memory_ids) > 0


# ---- search() ----

@pytest.mark.asyncio
async def test_search_returns_results(client):
    """search() returns SearchResults with memory hits."""
    await client.add("用户喜欢 TypeScript", entity_id="user_123")

    results = await client.search("TypeScript", entity_id="user_123")
    assert isinstance(results, SearchResults)
    assert len(results.results) > 0
    assert results.results[0].source in ("memory", "rag")


@pytest.mark.asyncio
async def test_search_modes(client):
    """search() supports hybrid, memory, and rag modes."""
    await client.add("用户喜欢 TypeScript", entity_id="user_123")

    # Memory mode
    mem = await client.search(
        "TypeScript", entity_id="user_123", search_mode="memory",
    )
    assert all(r.source == "memory" for r in mem.results)

    # Hybrid mode (default)
    hybrid = await client.search("TypeScript", entity_id="user_123")
    assert hybrid.search_mode == "hybrid"


@pytest.mark.asyncio
async def test_search_top_k(client):
    """search() respects top_k parameter."""
    await client.add("TypeScript 事实", entity_id="user_123")
    await client.add("Python 事实", entity_id="user_123")

    results = await client.search(
        "事实", entity_id="user_123", top_k=1,
    )
    assert len(results.results) <= 1


# ---- profile() ----

@pytest.mark.asyncio
async def test_profile_returns_profile(client):
    """profile() returns Profile with static + dynamic facts."""
    await client.add("用户是资深前端工程师", entity_id="user_123")
    await client.add("用户偏好 TypeScript", entity_id="user_123")

    profile = await client.profile("user_123")
    assert isinstance(profile, Profile)
    assert profile.entity_id == "user_123"
    assert profile.memory_count >= 2
    assert len(profile.static) >= 2


@pytest.mark.asyncio
async def test_profile_empty_entity(client):
    """profile() for unknown entity returns empty profile."""
    profile = await client.profile("unknown_entity")
    assert profile.entity_id == "unknown_entity"
    assert profile.memory_count == 0


# ---- Roundtrip: add → search ----

@pytest.mark.asyncio
async def test_add_then_search_roundtrip(client):
    """Content added via SDK is searchable."""
    content = "用户喜欢使用 Vim 编辑器进行开发"

    add_result = await client.add(content, entity_id="user_123")
    assert len(add_result.memory_ids) > 0

    search_results = await client.search("Vim 编辑器", entity_id="user_123")
    found = any("Vim" in r.content for r in search_results.results)
    assert found, f"Expected to find 'Vim' in results: {[r.content for r in search_results.results]}"


# ---- Entity isolation via SDK ----

@pytest.mark.asyncio
async def test_sdk_entity_isolation(client):
    """SDK respects entity boundaries."""
    await client.add("Alice 的秘密", entity_id="alice")
    await client.add("Bob 的公开信息", entity_id="bob")

    alice_results = await client.search("秘密", entity_id="alice")
    bob_results = await client.search("秘密", entity_id="bob")

    alice_texts = [r.content for r in alice_results.results]
    bob_texts = [r.content for r in bob_results.results]

    assert any("Alice" in t for t in alice_texts)
    assert not any("Alice" in t for t in bob_texts)


# ---- upload() ----

@pytest.mark.asyncio
async def test_upload_bytes(client):
    """upload() accepts bytes and returns pipeline_id."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.json.return_value = {
        "data": {
            "document_id": "doc_123",
            "pipeline_id": "pipe_456",
            "pipeline_status": "queued",
        }
    }
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.request.return_value = mock_response

    # I2 refactor: upload() reuses the shared client.  Inject the mock
    # directly rather than patching the constructor.
    original_client = client._client
    client._client = mock_http_client
    try:
        result = await client.upload(
            b"test file content",
            entity_id="user_123",
            title="test.txt",
        )
    finally:
        client._client = original_client
    assert isinstance(result, AddResult)
    assert result.pipeline_status == "queued"
    assert result.pipeline_id == "pipe_456"


@pytest.mark.asyncio
async def test_add_omits_content_type_when_undeclared(client):
    """content_type=None (default) must omit the field from the request body
    so the server-side sniffing can take effect (spec issue #1)."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "memory_ids": ["m1"],
            "pipeline_status": "done",
            "extracted_count": 1,
            "conflicts_pending": [],
        }
    }
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.request.return_value = mock_response

    original_client = client._client
    client._client = mock_http_client
    try:
        await client.add("hello", entity_id="user_123")
    finally:
        client._client = original_client

    _args, kwargs = mock_http_client.request.call_args
    assert "content_type" not in kwargs["json"], \
        "undeclared content_type must not default to 'text' on the wire"


@pytest.mark.asyncio
async def test_add_sends_explicit_content_type(client):
    """An explicitly declared content_type is forwarded in the body."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "memory_ids": ["m1"],
            "pipeline_status": "done",
            "extracted_count": 1,
            "conflicts_pending": [],
        }
    }
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.request.return_value = mock_response

    original_client = client._client
    client._client = mock_http_client
    try:
        await client.add("hello", entity_id="user_123", content_type="json")
    finally:
        client._client = original_client

    _args, kwargs = mock_http_client.request.call_args
    assert kwargs["json"]["content_type"] == "json"


@pytest.mark.asyncio
async def test_upload_str_path(tmp_path, client):
    """upload() accepts file path string."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.json.return_value = {
        "data": {
            "document_id": "doc_123",
            "pipeline_id": "pipe_789",
            "pipeline_status": "queued",
        }
    }
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.request.return_value = mock_response

    test_file = tmp_path / "test.md"
    test_file.write_text("# Hello")

    # I2 refactor: inject the mock client directly (see test_upload_bytes).
    original_client = client._client
    client._client = mock_http_client
    try:
        result = await client.upload(
            str(test_file),
            entity_id="user_123",
        )
    finally:
        client._client = original_client
    assert isinstance(result, AddResult)
    assert result.pipeline_status == "queued"


# ---- health() ----

@pytest.mark.asyncio
async def test_health_returns_status(client):
    """health() returns HealthStatus with checks."""
    status = await client.health()
    assert status.status in ("ok", "degraded")
    assert "version" in status.checks or status.version


# ---- pipeline_status() ----

@pytest.mark.asyncio
async def test_pipeline_status_not_found(client):
    """pipeline_status() for unknown pipeline raises."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.is_success = False
    mock_response.headers = {}
    mock_response.text = "Not found"
    mock_response.json.return_value = {"error": {"code": "NOT_FOUND", "message": "Not found"}}

    original_client = client._client
    client._client = AsyncMock()
    client._client.request = AsyncMock(return_value=mock_response)

    try:
        from emerald.sdk.exceptions import EmeraldNotFoundError
        with pytest.raises(EmeraldNotFoundError):
            await client.pipeline_status("nonexistent")
    finally:
        client._client = original_client


@pytest.mark.asyncio
async def test_pipeline_status_found(client):
    """pipeline_status() returns PipelineStatus for valid pipeline."""
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.headers = {}
    mock_response.json.return_value = {
        "data": {
            "pipeline_id": "pipe_123",
            "status": "done",
            "stage": "indexing",
            "document_id": "doc_456",
            "content_type": "pdf",
            "error_message": None,
        }
    }
    mock_response.raise_for_status = MagicMock()

    original_client = client._client
    client._client = AsyncMock()
    client._client.request = AsyncMock(return_value=mock_response)

    try:
        status = await client.pipeline_status("pipe_123")
        assert status.pipeline_id == "pipe_123"
        assert status.status == "done"
    finally:
        client._client = original_client


# ---- get_memory() ----

@pytest.mark.asyncio
async def test_get_memory_found(client):
    """get_memory() returns memory dict for existing memory."""
    add_result = await client.add("测试记忆", entity_id="user_123")
    mid = add_result.memory_ids[0]

    memory = await client.get_memory(mid)
    assert memory["id"] == mid
    assert "测试记忆" in memory["content"]


# ---- close() ----

@pytest.mark.asyncio
async def test_close_idempotent(client):
    """close() can be called multiple times safely."""
    await client.close()
    await client.close()  # should not raise
    assert client._client is None


# ---- SDK auth header ----

@pytest.mark.asyncio
async def test_client_sets_auth_header(client):
    """Client sets Authorization: Bearer header with API key."""
    assert client.api_key == "em_test123"
    assert client._headers["Authorization"] == "Bearer em_test123"
    assert client._headers["Content-Type"] == "application/json"


# ---- init from env ----

def test_client_reads_env(monkeypatch):
    """Client reads api_key and base_url from environment."""
    monkeypatch.setenv("EMERALD_API_KEY", "em_env_key")
    monkeypatch.setenv("EMERALD_BASE_URL", "http://env.test")

    c = EmeraldClient()
    assert c.api_key == "em_env_key"
    assert c.base_url == "http://env.test"


# ---- Entity-centric retrieval (B4, ticket #30) ----

@pytest.mark.asyncio
async def test_search_about_param_sent_in_body(client, engine):
    """SDK search(about=...) forwards the param to the REST body."""
    import asyncio as _asyncio

    from emerald.core.mentions import Mention

    async def _seed():
        mid = await engine.graph.create_memory("在 Google 工作", entity_id="user_1")
        await engine.graph.attach_mentions(
            mid, "user_1", [Mention("Google", "Google", "organization", 0.9)],
        )

    await _seed()

    results = await client.search(
        "关于 Google 的一切", entity_id="user_1", about="Google",
    )
    assert len(results.results) == 1
    assert results.results[0].content == "在 Google 工作"
