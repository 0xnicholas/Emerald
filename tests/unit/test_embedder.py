"""Unit tests for embedding providers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emerald.core.embedder import (
    FastembedProvider,
    MockEmbeddingProvider,
    OpenAIProvider,
    SentenceTransformersProvider,
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


@pytest.mark.asyncio
async def test_openai_cache_hit_skips_api_call(openai_provider):
    """Second call with same text returns cached vector, no API call."""
    import json
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.2] * 1536}]
    }

    with patch("emerald.db.redis.get_redis_client", return_value=fake_redis):
        with patch.object(
            openai_provider._client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response
            # First call — hits API
            r1 = await openai_provider.embed(["cached_text"])
            # Second call — should hit cache
            r2 = await openai_provider.embed(["cached_text"])

    assert mock_post.call_count == 1  # Only one API call
    assert r1 == r2


def test_fallback_when_key_missing(monkeypatch):
    """OPENAI_API_KEY empty → try FastembedProvider, then MockEmbeddingProvider."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    # Must reload settings cache
    from emerald.config import get_settings
    get_settings.cache_clear()

    p = get_embedding_provider()
    # If fastembed is installed, use it; otherwise fall back to Mock
    try:
        import fastembed  # noqa: F401
        assert isinstance(p, FastembedProvider)
    except ImportError:
        assert isinstance(p, MockEmbeddingProvider)
        assert p.dimension() == 384

    # Restore settings for other tests
    get_settings.cache_clear()


# ---- FastembedProvider tests ----


@pytest.mark.asyncio
async def test_fastembed_produces_semantic_embeddings():
    """FastembedProvider returns real semantic vectors."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    provider = FastembedProvider()
    assert provider.dimension() >= 384

    embeddings = await provider.embed(["hello world", "goodbye world"])
    assert len(embeddings) == 2
    assert len(embeddings[0]) == provider.dimension()

    # Semantic similarity: similar texts should be closer than dissimilar
    import math

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    sim_similar = cosine(embeddings[0], embeddings[1])

    # Very different text
    diff_emb = await provider.embed(["quantum physics and black holes"])
    sim_diff = cosine(embeddings[0], diff_emb[0])

    # Similar texts (both contain "world") should be closer than very different texts
    assert sim_similar > sim_diff, (
        f"Expected similar texts ({sim_similar:.3f}) > different ({sim_diff:.3f})"
    )


@pytest.mark.asyncio
async def test_fastembed_empty_batch():
    """Empty text list returns empty result."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    provider = FastembedProvider()
    assert await provider.embed([]) == []


@pytest.mark.asyncio
async def test_fastembed_custom_model():
    """Custom model name is respected."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    provider = FastembedProvider(model_name="BAAI/bge-small-en-v1.5")
    assert provider.dimension() == 384


@pytest.mark.asyncio
async def test_fastembed_dimension_before_embed():
    """dimension() works before any embed() call (lazy init)."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    provider = FastembedProvider()
    # Should trigger lazy model load
    assert provider.dimension() == 384


@pytest.mark.asyncio
async def test_fastembed_import_error_graceful():
    """When fastembed is not importable, FastembedProvider raises ImportError on first use."""
    with patch.dict("sys.modules", {"fastembed": None}):
        provider = FastembedProvider()
        with pytest.raises(ImportError, match="fastembed"):
            await provider.embed(["test"])


# ---- SentenceTransformersProvider tests (keep for backward compat) ----


@pytest.mark.asyncio
async def test_sentence_transformers_import_error():
    """When sentence-transformers is not installed, provider raises ImportError."""
    with patch.dict("sys.modules", {"sentence_transformers": None}):
        with pytest.raises(ImportError, match="sentence-transformers"):
            SentenceTransformersProvider()
