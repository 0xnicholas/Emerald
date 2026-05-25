"""Tests for SearchOrchestrator — hybrid search across memory + RAG."""

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore


@pytest.fixture
def embedder():
    return MockEmbeddingProvider(dimension=128)


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def vector():
    return VectorStore(use_db=False)


@pytest.fixture
async def orchestrator(graph, vector, embedder):
    return SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)


@pytest.fixture
async def populated(orchestrator, graph, vector, embedder):
    """Populate with test memories across two entities."""
    # Alice: tech person
    memories = [
        ("alice", "Alice 喜欢 TypeScript 和函数式编程", "preference"),
        ("alice", "Alice 是一名资深前端工程师", "fact"),
        ("alice", "Alice 住在北京朝阳区", "fact"),
        ("bob", "Bob 喜欢 Rust 和系统编程", "preference"),
        ("bob", "Bob 是一名后端工程师", "fact"),
    ]
    for entity_id, content, mtype in memories:
        mid = await graph.create_memory(content, entity_id=entity_id, memory_type=mtype)
        emb = (await embedder.embed([content]))[0]
        await vector.store(mid, content, emb, entity_id=entity_id)
    return orchestrator


# ---- Search modes ----

@pytest.mark.asyncio
async def test_search_memory_mode( populated):
    """search_mode=memory returns only graph memories."""
    results = await populated.search(
        "TypeScript", entity_id="alice", search_mode=SearchMode.MEMORY,
    )
    assert len(results.results) > 0
    for r in results.results:
        assert r.source == "memory"


@pytest.mark.asyncio
async def test_search_rag_mode(populated):
    """search_mode=rag returns only vector results."""
    # Exact match query for mock embeddings
    results = await populated.search(
        "Alice 是一名资深前端工程师",
        entity_id="alice",
        search_mode=SearchMode.RAG,
    )
    assert len(results.results) > 0
    for r in results.results:
        assert r.source == "rag"


@pytest.mark.asyncio
async def test_search_hybrid_mode(populated):
    """search_mode=hybrid returns both memory and rag results.

    Uses exact-match queries because mock embeddings are hash-based
    and don't capture semantic similarity. Real embeddings would match
    semantically related queries too.
    """
    # Query with text that exactly matches stored content
    results = await populated.search(
        "Alice 喜欢 TypeScript 和函数式编程",
        entity_id="alice",
        search_mode=SearchMode.HYBRID,
    )
    sources = {r.source for r in results.results}
    assert "memory" in sources
    assert "rag" in sources


# ---- Entity isolation ----

@pytest.mark.asyncio
async def test_search_entity_isolation(populated):
    """Search for one entity does not return another entity's memories."""
    results = await populated.search(
        "Rust", entity_id="alice", search_mode=SearchMode.HYBRID,
    )
    for r in results.results:
        assert "Bob" not in r.content


# ---- Score ordering ----

@pytest.mark.asyncio
async def test_results_sorted_by_score(populated):
    """Results are returned in descending score order."""
    results = await populated.search(
        "TypeScript", entity_id="alice", search_mode=SearchMode.HYBRID, top_k=5,
    )
    scores = [r.score for r in results.results]
    assert scores == sorted(scores, reverse=True)


# ---- Deduplication ----

@pytest.mark.asyncio
async def test_hybrid_deduplicates(populated, graph, vector, embedder):
    """Same content found in both memory and RAG is deduplicated."""
    content = "用户精通 Python 和机器学习"
    mid = await graph.create_memory(content, entity_id="alice")
    emb = (await embedder.embed([content]))[0]
    await vector.store(mid, content, emb, entity_id="alice")

    results = await populated.search(
        "Python 机器学习", entity_id="alice", search_mode=SearchMode.HYBRID, top_k=10,
    )
    # Check for duplicates by ID
    ids = [r.id for r in results.results]
    assert len(ids) == len(set(ids))


# ---- Top-k limit ----

@pytest.mark.asyncio
async def test_top_k_respected(populated):
    """top_k parameter limits result count."""
    results = await populated.search(
        "工程师", entity_id="alice", search_mode=SearchMode.HYBRID, top_k=1,
    )
    assert len(results.results) <= 1


# ---- Empty results ----

@pytest.mark.asyncio
async def test_memory_search_empty_for_unrelated(populated):
    """Memory (keyword) search returns empty for unmatched queries."""
    results = await populated.search(
        "量子计算 黑洞 相对论", entity_id="alice", search_mode=SearchMode.MEMORY,
    )
    # Memory search is keyword-based, so unrelated queries yield no results
    assert len(results.results) == 0
