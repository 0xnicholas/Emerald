"""Unit tests for MockEmbeddingProvider."""

import pytest

from emerald.core.embedder import MockEmbeddingProvider


@pytest.fixture
def embedder():
    return MockEmbeddingProvider(dimension=128)


@pytest.mark.asyncio
async def test_mock_embedder_returns_correct_dimension(embedder):
    """Each embedding vector has the configured dimension."""
    embeddings = await embedder.embed(["hello", "world"])
    assert len(embeddings) == 2
    for emb in embeddings:
        assert len(emb) == 128


@pytest.mark.asyncio
async def test_mock_embedder_deterministic(embedder):
    """Same input always produces the same vector."""
    emb1 = await embedder.embed(["hello"])
    emb2 = await embedder.embed(["hello"])
    assert emb1[0] == emb2[0]


@pytest.mark.asyncio
async def test_mock_embedder_different_inputs_different_vectors(embedder):
    """Different inputs produce different vectors."""
    emb1 = (await embedder.embed(["hello"]))[0]
    emb2 = (await embedder.embed(["world"]))[0]
    assert emb1 != emb2


@pytest.mark.asyncio
async def test_mock_embedder_empty_list(embedder):
    """Empty input list returns empty output."""
    result = await embedder.embed([])
    assert result == []


@pytest.mark.asyncio
async def test_mock_embedder_dimension_property(embedder):
    """dimension() returns the configured value."""
    assert embedder.dimension() == 128


@pytest.mark.asyncio
async def test_mock_embedder_values_in_range(embedder):
    """All embedding values are in [-1, 1]."""
    embeddings = await embedder.embed(["test text here"])
    for val in embeddings[0]:
        assert -1.0 <= val <= 1.0
