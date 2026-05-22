"""Unit tests for VectorStore (in-memory mode)."""

import pytest

from emerald.core.vector import VectorStore


@pytest.fixture
def store():
    return VectorStore(use_db=False)


@pytest.mark.asyncio
async def test_store_and_search(store):
    """Stored embeddings are searchable."""
    emb = [0.1, 0.2, 0.3]
    await store.store("chunk_1", "hello world", emb, entity_id="user_1")

    results = await store.search(emb, entity_id="user_1", top_k=5)
    assert len(results) == 1
    chunk_id, text, score = results[0]
    assert chunk_id == "chunk_1"
    assert text == "hello world"
    assert score == pytest.approx(1.0, abs=0.01)  # Same vector = cosine 1.0


@pytest.mark.asyncio
async def test_cosine_similarity_identical(store):
    """Same vector has cosine similarity 1.0."""
    emb = [0.5] * 10
    score = store._cosine_similarity(emb, emb)
    assert score == pytest.approx(1.0, abs=0.01)


@pytest.mark.asyncio
async def test_cosine_similarity_orthogonal(store):
    """Orthogonal vectors have cosine similarity 0."""
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    score = store._cosine_similarity(a, b)
    assert score == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_cosine_similarity_opposite(store):
    """Opposite vectors have cosine similarity -1."""
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    score = store._cosine_similarity(a, b)
    assert score == pytest.approx(-1.0, abs=0.01)


@pytest.mark.asyncio
async def test_cosine_similarity_zero_vector(store):
    """Zero vector returns 0 (degenerate case)."""
    score = store._cosine_similarity([0.0, 0.0], [1.0, 0.0])
    assert score == 0.0


@pytest.mark.asyncio
async def test_search_respects_entity_id(store):
    """Search only returns results for the specified entity."""
    emb = [0.1, 0.2]
    await store.store("c1", "alice's", emb, entity_id="alice")
    await store.store("c2", "bob's", emb, entity_id="bob")

    alice_results = await store.search(emb, entity_id="alice", top_k=5)
    assert len(alice_results) == 1
    assert alice_results[0][1] == "alice's"


@pytest.mark.asyncio
async def test_search_respects_top_k(store):
    """top_k limits the number of results."""
    emb = [0.1, 0.2]
    for i in range(5):
        await store.store(f"c{i}", f"text {i}", emb, entity_id="user_1")

    results = await store.search(emb, entity_id="user_1", top_k=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_empty_store(store):
    """Searching an empty store returns empty list."""
    results = await store.search([0.1], entity_id="user_1")
    assert results == []


@pytest.mark.asyncio
async def test_results_sorted_by_score_descending(store):
    """Results are returned in descending similarity order."""
    query = [1.0, 0.0, 0.0]

    # Best match: same direction
    await store.store("c1", "best", [1.0, 0.0, 0.0], entity_id="user_1")
    # Medium: somewhat similar
    await store.store("c2", "medium", [1.0, 1.0, 0.0], entity_id="user_1")
    # Worst: different direction
    await store.store("c3", "worst", [0.0, 1.0, 0.0], entity_id="user_1")

    results = await store.search(query, entity_id="user_1", top_k=3)
    scores = [score for _, _, score in results]
    assert scores[0] >= scores[1] >= scores[2]
