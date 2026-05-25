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
