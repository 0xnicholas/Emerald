"""Tests for SearchOrchestrator — hybrid search across memory + RAG."""

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator, SearchResult
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
async def test_search_memory_mode(populated):
    """search_mode=memory returns only graph memories."""
    # Exact match because MockEmbeddingProvider is hash-based
    results = await populated.search(
        "Alice 喜欢 TypeScript 和函数式编程",
        entity_id="alice",
        search_mode=SearchMode.MEMORY,
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
    """Semantic search returns empty for entities with no memories."""
    results = await populated.search(
        "量子计算 黑洞 相对论", entity_id="charlie", search_mode=SearchMode.MEMORY,
    )
    assert len(results.results) == 0


# ---- Query rewriting stub ----

@pytest.mark.asyncio
async def test_rewrite_query_false_returns_original(populated):
    """When rewrite_query=False, query_rewritten is None."""
    results = await populated.search(
        "Python", entity_id="alice", search_mode=SearchMode.MEMORY, rewrite_query=False,
    )
    assert results.query_rewritten is None


@pytest.mark.asyncio
async def test_rewrite_query_expands_short_query(populated):
    """When rewrite_query=True, short queries are expanded."""
    results = await populated.search(
        "Python", entity_id="alice", search_mode=SearchMode.MEMORY, rewrite_query=True,
    )
    assert results.query_rewritten is not None
    assert "Python" in results.query_rewritten
    assert "相关信息" in results.query_rewritten


@pytest.mark.asyncio
async def test_rewrite_query_expands_howto(populated):
    """Pattern-based expansion for '如何' queries."""
    results = await populated.search(
        "如何部署", entity_id="alice", search_mode=SearchMode.MEMORY, rewrite_query=True,
    )
    assert "方法" in results.query_rewritten
    assert "步骤" in results.query_rewritten


@pytest.mark.asyncio
async def test_rewrite_query_noop_for_long_query(populated):
    """Long queries without patterns are returned as-is."""
    long_query = "这是一个非常长的查询语句用来测试查询重写器不会对超过十个字符的查询进行无意义的扩展"
    results = await populated.search(
        long_query, entity_id="alice", search_mode=SearchMode.MEMORY, rewrite_query=True,
    )
    assert results.query_rewritten == long_query


# ---- Rerank stub ----

def test_rerank_boosts_keyword_matches():
    """_rerank_results boosts results with direct keyword overlap."""
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="Alice 住在北京朝阳区", score=0.9, source="memory"),
        SearchResult(id="2", content="Alice 喜欢 TypeScript 和函数式编程", score=0.8, source="memory"),
    ]
    reranked = orchestrator._rerank_results(results, "TypeScript")
    # The TypeScript result should move ahead despite lower initial score
    assert reranked[0].id == "2"


def test_rerank_no_overlap_unchanged():
    """_rerank_results preserves order when no keyword overlap."""
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="Alice 住在北京朝阳区", score=0.9, source="memory"),
        SearchResult(id="2", content="Bob 喜欢 Rust", score=0.8, source="memory"),
    ]
    reranked = orchestrator._rerank_results(results, "量子计算")
    assert reranked[0].id == "1"
    assert reranked[1].id == "2"
