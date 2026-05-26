"""Unit tests for embedding providers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emerald.core.embedder import (
    MockEmbeddingProvider,
    OpenAIProvider,
    get_embedding_provider,
)


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider(dimension=128)


# ---- MockEmbeddingProvider tests ----

@pytest.mark.asyncio
async def test_mock_embedder_returns_correct_dimension(mock_embedder):
    embeddings = await mock_embedder.embed(["hello", "world"])
    assert len(embeddings) == 2
    for emb in embeddings:
        assert len(emb) == 128


@pytest.mark.asyncio
async def test_mock_embedder_deterministic(mock_embedder):
    emb1 = await mock_embedder.embed(["hello"])
    emb2 = await mock_embedder.embed(["hello"])
    assert emb1[0] == emb2[0]


@pytest.mark.asyncio
async def test_mock_embedder_empty_list(mock_embedder):
    assert await mock_embedder.embed([]) == []


# ---- OpenAIProvider tests ----

@pytest.fixture
def openai_provider():
    return OpenAIProvider(api_key="sk-test", model="text-embedding-3-small")


@pytest.mark.asyncio
async def test_openai_embed_returns_correct_dimension(openai_provider):
    """OpenAI embed returns 1536-dim vectors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.1] * 1536}]
    }

    with patch.object(openai_provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await openai_provider.embed(["hello"])

    assert len(result) == 1
    assert len(result[0]) == 1536
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_openai_embed_batches_large_input(openai_provider):
    """2500 texts → 2 API calls (batch size 2048)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    texts = [f"text_{i}" for i in range(2500)]
    # Return embeddings for all texts in the batch
    def make_batch_response(batch):
        return {
            "data": [
                {"index": i, "embedding": [0.01 * i] * 1536}
                for i in range(len(batch))
            ]
        }

    call_count = 0
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        batch = kwargs["json"]["input"]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = make_batch_response(batch)
        return resp

    with patch.object(openai_provider._client, "post", side_effect=mock_post):
        result = await openai_provider.embed(texts)

    assert call_count == 2
    assert len(result) == 2500


@pytest.mark.asyncio
async def test_openai_embed_retries_on_502(openai_provider):
    """Mock 502 → retry → success."""
    fail_response = MagicMock()
    fail_response.status_code = 502
    fail_response.text = "Bad Gateway"

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.1] * 1536}]
    }

    with patch.object(
        openai_provider._client, "post", new_callable=AsyncMock
    ) as mock_post:
        mock_post.side_effect = [fail_response, ok_response]
        result = await openai_provider.embed(["hello"])

    assert len(result) == 1
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_openai_embed_raises_after_max_retries(openai_provider):
    """3 failures → EmbeddingError."""
    fail_response = MagicMock()
    fail_response.status_code = 503
    fail_response.text = "Service Unavailable"

    with patch.object(
        openai_provider._client, "post", new_callable=AsyncMock
    ) as mock_post:
        mock_post.return_value = fail_response
        with pytest.raises(Exception):  # Will refine after defining EmbeddingError
            await openai_provider.embed(["hello"])

    assert mock_post.call_count == 3  # initial + 2 retries
