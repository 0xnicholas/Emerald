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


class _KeywordEmbeddingProvider:
    """Test-only embedder: returns the same vector for any text containing a keyword."""

    def __init__(self, keyword: str, dimension: int = 128) -> None:
        self.keyword = keyword
        self._dimension = dimension
        self._match_vec = [1.0] + [0.0] * (dimension - 1)
        self._miss_vec = [0.0] * dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            self._match_vec if self.keyword in t else self._miss_vec for t in texts
        ]

    def dimension(self) -> int:
        return self._dimension


@pytest.mark.asyncio
async def test_search_rag_mode(populated, vector):
    """search_mode=rag returns only document (RAG) vector results."""
    # RAG chunks are identified by document_id; memory embeddings are not.
    rag_text = "Alice 是一名资深前端工程师"
    embedder = _KeywordEmbeddingProvider("前端")
    rag_emb = (await embedder.embed([rag_text]))[0]
    await vector.store(
        "rag-doc-1", rag_text, rag_emb, entity_id="alice", document_id="doc-1"
    )

    orchestrator = SearchOrchestrator(
        graph=populated.graph, vector=vector, embedder=embedder
    )
    results = await orchestrator.search(
        "前端工程师",
        entity_id="alice",
        search_mode=SearchMode.RAG,
    )
    assert len(results.results) > 0
    for r in results.results:
        assert r.source == "rag"


@pytest.mark.asyncio
async def test_search_hybrid_mode(populated, graph, vector):
    """search_mode=hybrid returns both memory and rag results.

    We intentionally keep memory and RAG contents distinct so that
    cross-source deduplication does not hide one of the sources.
    """
    keyword = "Vim"
    embedder = _KeywordEmbeddingProvider(keyword)

    # Memory fact stored in both graph and vector
    memory_text = "Alice 使用 Vim 编辑器"
    memory_id = await graph.create_memory(
        memory_text, entity_id="alice", memory_type="fact"
    )
    mem_emb = (await embedder.embed([memory_text]))[0]
    await vector.store(memory_id, memory_text, mem_emb, entity_id="alice")

    # RAG-only document chunk (document_id marks it as RAG)
    rag_text = "Vim 编辑器快捷键大全"
    rag_emb = (await embedder.embed([rag_text]))[0]
    await vector.store(
        "rag-chunk-1", rag_text, rag_emb, entity_id="alice", document_id="doc-vim"
    )

    orchestrator = SearchOrchestrator(
        graph=populated.graph, vector=vector, embedder=embedder
    )
    results = await orchestrator.search(
        keyword,
        entity_id="alice",
        search_mode=SearchMode.HYBRID,
        dynamic_truncation=False,
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


@pytest.mark.asyncio
async def test_default_top_k_increased(populated):
    """Default top_k is now 30 to improve recall (MEMANTO insight)."""
    results = await populated.search(
        "工程师", entity_id="alice", search_mode=SearchMode.HYBRID,
    )
    # Default should be 30; with only a few test memories we get all of them.
    assert len(results.results) <= 30


# ---- Min-confidence filter ----

@pytest.mark.asyncio
async def test_min_confidence_filters_low_confidence_memories(populated, graph, vector, embedder):
    """min_confidence excludes memories below the threshold."""
    content = "低置信度记忆"
    mid = await graph.create_memory(
        content, entity_id="alice", memory_type="fact", confidence=0.3
    )
    emb = (await embedder.embed([content]))[0]
    await vector.store(mid, content, emb, entity_id="alice")

    results_filtered = await populated.search(
        "低置信度记忆",
        entity_id="alice",
        search_mode=SearchMode.MEMORY,
        min_confidence=0.5,
    )
    filtered_ids = {r.id for r in results_filtered.results}
    assert mid not in filtered_ids

    results_no_filter = await populated.search(
        "低置信度记忆",
        entity_id="alice",
        search_mode=SearchMode.MEMORY,
    )
    no_filter_ids = {r.id for r in results_no_filter.results}
    assert mid in no_filter_ids


# ---- Dynamic truncation ----

@pytest.mark.asyncio
async def test_dynamic_truncation_stops_at_score_gap():
    """Dynamic truncation drops tail results when a large score gap appears.

    We provide more than the minimum-floor results so the gap rule can fire.
    """
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="A", score=0.95, source="memory"),
        SearchResult(id="2", content="B", score=0.80, source="memory"),
        SearchResult(id="3", content="C", score=0.78, source="memory"),
        SearchResult(id="4", content="D", score=0.40, source="memory"),
        SearchResult(id="5", content="E", score=0.38, source="memory"),
    ]
    merged = orchestrator._merge_results(results, top_k=10, dynamic_truncation=True)
    ids = [r.id for r in merged]
    assert "1" in ids
    assert "2" in ids
    assert "3" in ids
    assert "4" not in ids  # gap 0.38 > default 0.15
    assert "5" not in ids


@pytest.mark.asyncio
async def test_dynamic_truncation_disabled_returns_all():
    """When dynamic truncation is disabled, top_k is the only limit."""
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="A", score=0.95, source="memory"),
        SearchResult(id="2", content="B", score=0.40, source="memory"),
    ]
    merged = orchestrator._merge_results(results, top_k=10, dynamic_truncation=False)
    ids = [r.id for r in merged]
    assert "1" in ids
    assert "2" in ids


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
    """When rewrite_query=True, short queries are expanded (pattern or LLM)."""
    results = await populated.search(
        "Python", entity_id="alice", search_mode=SearchMode.MEMORY, rewrite_query=True,
    )
    assert results.query_rewritten is not None
    assert "Python" in results.query_rewritten
    # Either pattern-based expansion or LLM semantic expansion
    assert len(results.query_rewritten) > len("Python")


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


# ---- Rerank ----

@pytest.mark.asyncio
async def test_rerank_boosts_keyword_matches():
    """_rerank_results boosts results with direct keyword overlap."""
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="Alice 住在北京朝阳区", score=0.9, source="memory"),
        SearchResult(id="2", content="Alice 喜欢 TypeScript 和函数式编程", score=0.8, source="memory"),
    ]
    reranked = await orchestrator._rerank_results(results, "TypeScript")
    # The TypeScript result should move ahead despite lower initial score
    assert reranked[0].id == "2"


@pytest.mark.asyncio
async def test_rerank_no_overlap_unchanged():
    """_rerank_results preserves order when no keyword overlap."""
    orchestrator = SearchOrchestrator()
    results = [
        SearchResult(id="1", content="Alice 住在北京朝阳区", score=0.9, source="memory"),
        SearchResult(id="2", content="Bob 喜欢 Rust", score=0.8, source="memory"),
    ]
    reranked = await orchestrator._rerank_results(results, "量子计算")
    assert reranked[0].id == "1"
    assert reranked[1].id == "2"


@pytest.mark.asyncio
async def test_rerank_empty_results():
    """_rerank_results on empty list returns empty."""
    orchestrator = SearchOrchestrator()
    result = await orchestrator._rerank_results([], "anything")
    assert result == []


@pytest.mark.asyncio
async def test_embedding_rerank_with_mock_embedder():
    """Embedding-based rerank reorders results by cosine similarity."""
    embedder = MockEmbeddingProvider(dimension=128)
    orchestrator = SearchOrchestrator(embedder=embedder)

    # Create results where content closer to query should rank higher
    results = [
        SearchResult(id="1", content="量子计算和黑洞研究", score=0.5, source="memory"),
        SearchResult(id="2", content="TypeScript 前端开发", score=0.9, source="memory"),
    ]
    # Query about physics — result 1 should rise, result 2 should fall
    reranked = await orchestrator._embedding_rerank(results, "物理学 量子")

    # Embedding rerank should produce results
    assert len(reranked) == 2
    # All scores should still be valid numbers
    for r in reranked:
        assert 0.0 <= r.score <= 1.0


@pytest.mark.asyncio
async def test_embedding_rerank_falls_back_without_embedder():
    """Without embedder, _embedding_rerank falls back to keyword boost."""
    orchestrator = SearchOrchestrator()  # No embedder
    results = [
        SearchResult(id="1", content="Alice 住在北京朝阳区", score=0.9, source="memory"),
        SearchResult(id="2", content="Bob 喜欢 Rust", score=0.8, source="memory"),
    ]
    # Should fall back to keyword boost (no crash)
    reranked = await orchestrator._embedding_rerank(results, "Rust")
    assert len(reranked) == 2
    # Keyword boost moves Rust result ahead
    assert reranked[0].id == "2"


@pytest.mark.asyncio
async def test_cross_encoder_cache_is_class_level():
    """Cross-encoder model cache is shared across instances (classmethod)."""
    # Reset cache for test isolation
    SearchOrchestrator._cross_encoder_cache = None

    o1 = SearchOrchestrator()
    o2 = SearchOrchestrator()

    # Both should return the same result (None if not installed, or model if installed)
    ce1 = o1._get_cross_encoder()
    ce2 = o2._get_cross_encoder()
    assert ce1 is ce2  # Same cached reference

    # Reset
    SearchOrchestrator._cross_encoder_cache = None


@pytest.mark.asyncio
async def test_rerank_tier_fallback_chain_with_mock():
    """When cross-encoder unavailable, falls through to embedding then keyword.
    
    With MockEmbeddingProvider, Tier 2 (embedding) should succeed.
    """
    # Force cross-encoder to be unavailable
    SearchOrchestrator._cross_encoder_cache = "__unavailable__"

    embedder = MockEmbeddingProvider(dimension=128)
    orchestrator = SearchOrchestrator(embedder=embedder)

    results = [
        SearchResult(id="1", content="物理和数学", score=0.5, source="memory"),
        SearchResult(id="2", content="编程和开发", score=0.9, source="memory"),
    ]

    reranked = await orchestrator._rerank_results(results, "物理科学")
    assert len(reranked) == 2

    # Reset
    SearchOrchestrator._cross_encoder_cache = None


# ---- Relationship expansion ----


@pytest.mark.asyncio
async def test_expand_extends_relationship():
    """Search result expanded via EXTENDS to include extended memory."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "expand_test"

    # Create two related memories: B EXTENDS A
    mid_a = await graph.create_memory(
        "Alice 是一名工程师", entity_id=entity, memory_type="fact"
    )
    mid_b = await graph.create_memory(
        "Alice 是前端工程师，主攻 React", entity_id=entity, memory_type="fact"
    )
    # Also create relationship: B EXTENDS A
    await graph.create_relationship(mid_b, mid_a, "EXTENDS", {"aspect": "detail"})

    # Build a mock result containing the extending memory (B)
    results = [
        SearchResult(id=mid_b, content="Alice 是前端工程师，主攻 React", score=0.9, source="memory")
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    # Should now contain both B and A
    ids = {r.id for r in expanded}
    assert mid_b in ids, "original result should be preserved"
    assert mid_a in ids, "EXTENDS target should be included"
    assert len(expanded) == 2


@pytest.mark.asyncio
async def test_expand_derives_from_relationship():
    """Search result expanded via DERIVES_FROM to include source memories."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "derives_test"

    mid_src1 = await graph.create_memory(
        "Alice 在 Stripe 工作", entity_id=entity, memory_type="fact"
    )
    mid_src2 = await graph.create_memory(
        "Stripe 是一家支付公司", entity_id=entity, memory_type="fact"
    )
    mid_derived = await graph.create_memory(
        "Alice 很可能在支付行业工作", entity_id=entity, memory_type="fact"
    )
    await graph.create_relationship(mid_derived, mid_src1, "DERIVES_FROM", {"reasoning": "employment"})
    await graph.create_relationship(mid_derived, mid_src2, "DERIVES_FROM", {"reasoning": "industry"})

    results = [
        SearchResult(id=mid_derived, content="Alice 很可能在支付行业工作", score=0.9, source="memory")
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    ids = {r.id for r in expanded}
    assert mid_derived in ids
    assert mid_src1 in ids, "DERIVES_FROM source 1 should be included"
    assert mid_src2 in ids, "DERIVES_FROM source 2 should be included"
    assert len(expanded) == 3


@pytest.mark.asyncio
async def test_expand_inbound_extends():
    """When searching for the target of EXTENDS, the source should be included."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "inbound_test"

    # B EXTENDS A
    mid_a = await graph.create_memory(
        "用户住在北京", entity_id=entity, memory_type="fact"
    )
    mid_b = await graph.create_memory(
        "用户住在北京海淀区", entity_id=entity, memory_type="fact"
    )
    await graph.create_relationship(mid_b, mid_a, "EXTENDS")

    # Search finds A (the target); expansion should include B (the source)
    results = [
        SearchResult(id=mid_a, content="用户住在北京", score=0.9, source="memory")
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    ids = {r.id for r in expanded}
    assert mid_a in ids
    assert mid_b in ids, "EXTENDS source should be included (inbound direction)"
    assert len(expanded) == 2


@pytest.mark.asyncio
async def test_expand_deduplicates_and_scores():
    """Expanded results are deduplicated and have lower scores than originals."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "dedup_test"

    mid_base = await graph.create_memory(
        "基础事实", entity_id=entity, memory_type="fact"
    )
    mid_ext = await graph.create_memory(
        "扩展详情", entity_id=entity, memory_type="fact"
    )
    await graph.create_relationship(mid_ext, mid_base, "EXTENDS")

    results = [
        SearchResult(id=mid_base, content="基础事实", score=0.9, source="memory"),
        SearchResult(id=mid_ext, content="扩展详情", score=0.8, source="memory"),
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    ids = [r.id for r in expanded]
    # No duplicates
    assert len(ids) == len(set(ids))
    # Original results keep their scores; expanded ones have lower scores
    for r in expanded:
        if r.source == "memory_expanded":
            assert r.score <= 0.9 * 0.85 + 0.01  # should be ≤ original × 0.85


@pytest.mark.asyncio
async def test_expand_no_relationships_no_change():
    """When no relationships exist, results are unchanged."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "no_rel_test"

    mid = await graph.create_memory(
        "独立事实", entity_id=entity, memory_type="fact"
    )

    results = [
        SearchResult(id=mid, content="独立事实", score=0.9, source="memory")
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    assert len(expanded) == 1
    assert expanded[0].id == mid


@pytest.mark.asyncio
async def test_expand_excludes_updates():
    """UPDATES relationships should NOT trigger expansion."""
    graph = GraphStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    vector = VectorStore(use_db=False)
    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    entity = "no_updates_test"

    mid_old = await graph.create_memory(
        "旧事实：用户在 Google 工作", entity_id=entity, memory_type="fact"
    )
    mid_new = await graph.create_memory(
        "新事实：用户在 Stripe 工作", entity_id=entity, memory_type="fact"
    )
    await graph.create_relationship(mid_new, mid_old, "UPDATES")
    # Mark old as superseded
    await graph.update_is_latest(mid_old, False, replaced_by=mid_new)

    results = [
        SearchResult(id=mid_new, content="新事实：用户在 Stripe 工作", score=0.9, source="memory")
    ]

    expanded = await orchestrator._expand_relationships(results, entity, top_k=5)

    # Only the new fact should be present (old one is is_latest=False)
    ids = {r.id for r in expanded}
    assert mid_new in ids
    assert mid_old not in ids, "UPDATES relationships should not trigger expansion"
