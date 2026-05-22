"""Tests for Python SDK client."""

import pytest
import httpx
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.core.engine import MemoryEngine
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.core.extractor import ExtractorRegistry
from emerald.core.chunker import ChunkerRegistry
from emerald.pipeline.extraction.text import TextExtractor
from emerald.pipeline.chunking.text import TextChunker
from emerald.sdk import EmeraldClient
from emerald.sdk.models import AddResult, SearchResults, Profile


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
    app = create_app(engine=engine)
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


# ---- SDK auth header ----

@pytest.mark.asyncio
async def test_client_sets_auth_header(client):
    """Client sets Authorization: Bearer header with API key."""
    assert client.api_key == "em_test123"
    assert client._headers["Authorization"] == "Bearer em_test123"
    assert client._headers["Content-Type"] == "application/json"
