"""Unit tests for VectorStore (in-memory fallback mode)."""

import math

import pytest

from emerald.core.vector import VectorStore


@pytest.fixture
def vector():
    return VectorStore(use_db=False)


@pytest.mark.asyncio
async def test_store_and_search(vector):
    emb = [1.0, 0.0, 0.0]
    await vector.store("c1", "hello", emb, entity_id="e1")
    results = await vector.search(emb, entity_id="e1", top_k=5)
    assert len(results) == 1
    assert results[0][0] == "c1"


@pytest.mark.asyncio
async def test_cosine_similarity_identical(vector):
    a = [1.0, 2.0, 3.0]
    score = vector._cosine_similarity(a, a)
    assert math.isclose(score, 1.0, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_cosine_similarity_orthogonal(vector):
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    score = vector._cosine_similarity(a, b)
    assert math.isclose(score, 0.0, abs_tol=1e-9)


@pytest.mark.asyncio
async def test_search_respects_entity_id(vector):
    await vector.store("c1", "alice", [1.0, 0.0], entity_id="alice")
    await vector.store("c2", "bob", [1.0, 0.0], entity_id="bob")
    results = await vector.search([1.0, 0.0], entity_id="alice", top_k=5)
    assert all("bob" not in t for _, t, _ in results)


@pytest.mark.asyncio
async def test_search_respects_top_k(vector):
    for i in range(10):
        await vector.store(f"c{i}", f"text {i}", [1.0, 0.0], entity_id="e1")
    results = await vector.search([1.0, 0.0], entity_id="e1", top_k=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_cosine_similarity_opposite(vector):
    """Opposite vectors have cosine similarity -1."""
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    score = vector._cosine_similarity(a, b)
    assert math.isclose(score, -1.0, abs_tol=1e-9)


@pytest.mark.asyncio
async def test_cosine_similarity_zero_vector(vector):
    """Zero vector returns 0.0 (degenerate case)."""
    score = vector._cosine_similarity([0.0, 0.0], [1.0, 0.0])
    assert score == 0.0


@pytest.mark.asyncio
async def test_results_sorted_by_score_descending(vector):
    """Search results are returned in descending similarity order."""
    query = [1.0, 0.0, 0.0]
    await vector.store("c1", "best", [1.0, 0.0, 0.0], entity_id="e1")
    await vector.store("c2", "medium", [1.0, 1.0, 0.0], entity_id="e1")
    await vector.store("c3", "worst", [0.0, 1.0, 0.0], entity_id="e1")

    results = await vector.search(query, entity_id="e1", top_k=3)
    scores = [s for _, _, s in results]
    assert scores[0] >= scores[1] >= scores[2]


@pytest.mark.asyncio
async def test_search_empty_store(vector):
    results = await vector.search([1.0, 0.0], entity_id="e1", top_k=5)
    assert results == []


# ---- store_document_chunks: RAG 块幂等写入（#52 走查缺陷 A）----


@pytest.mark.asyncio
async def test_store_document_chunks_rag_searchable(vector):
    """文档块写入后 rag 态（require_document_id）可命中，memory 态不可见。"""
    doc_id = "d" * 8 + "-0000-0000-0000-" + "0" * 12
    texts = ["第一段文档内容", "第二段文档内容"]
    embs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    await vector.store_document_chunks(doc_id, texts, embs, entity_id="e1")

    rag_hits = await vector.search(embs[0], entity_id="e1", top_k=5, require_document_id=True)
    assert "第一段文档内容" in [t for _, t, _ in rag_hits]

    mem_hits = await vector.search(embs[0], entity_id="e1", top_k=5, memory_only=True)
    assert "第一段文档内容" not in [t for _, t, _ in mem_hits]


@pytest.mark.asyncio
async def test_store_document_chunks_idempotent(vector):
    """重复写入同文档 = 替换而非堆积（管线重试幂等）。"""
    doc_id = "d" * 8 + "-0000-0000-0000-" + "0" * 12
    texts = ["第一段文档内容", "第二段文档内容"]
    embs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    await vector.store_document_chunks(doc_id, texts, embs, entity_id="e1")
    await vector.store_document_chunks(doc_id, texts, embs, entity_id="e1")

    hits = await vector.search(embs[0], entity_id="e1", top_k=10, require_document_id=True)
    first_texts = [t for _, t, _ in hits if t == "第一段文档内容"]
    assert len(first_texts) == 1


@pytest.mark.asyncio
async def test_store_document_chunks_replaces_stale(vector):
    """重写文档时旧块被清除——不留陈旧内容。"""
    doc_id = "d" * 8 + "-0000-0000-0000-" + "0" * 12
    await vector.store_document_chunks(
        doc_id, ["旧内容"], [[1.0, 0.0, 0.0]], entity_id="e1",
    )
    await vector.store_document_chunks(
        doc_id, ["新内容"], [[1.0, 0.0, 0.0]], entity_id="e1",
    )
    hits = await vector.search([1.0, 0.0, 0.0], entity_id="e1", top_k=10, require_document_id=True)
    texts = [t for _, t, _ in hits]
    assert "新内容" in texts
    assert "旧内容" not in texts
