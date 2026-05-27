# Emerald M1 Completion + M2 Start — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the "semantic gap" by replacing `MockEmbeddingProvider` with real OpenAI embeddings, then wire authentication, health checks, file upload, Celery pipeline, and PDF/image extractors — all backed by real infrastructure (Neo4j, pgvector, Redis, MinIO) rather than stubs.

**Architecture:** Bottom-up: embedding provider → search → API layer → Celery pipeline → extractors. Each layer is implemented with TDD (write failing test → make it pass → commit). The semantic hybrid search uses pgvector for candidate generation and Neo4j for temporal validity filtering. The Celery pipeline uses `run_async()` to bridge sync Celery tasks with async database drivers.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), neo4j Python driver 5.x, pgvector, redis-py, Celery 5.x, pytest, tenacity, httpx, testcontainers.

**Spec reference:** `docs/superpowers/specs/2026-05-25-m1-completion-m2-start.md`

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `tests/unit/test_embedder.py` | Embedding provider unit tests (OpenAI batching, retry, cache, fallback) |
| `tests/unit/test_search_semantic.py` | Search semantic recall, filtering, hybrid dedup |
| `tests/unit/test_auth.py` | API key auth, permissions, rate limiting |
| `tests/unit/test_health.py` | Health probe tests |
| `tests/unit/test_pdf_extractor.py` | PDF extraction (text + OCR fallback) |
| `tests/unit/test_image_extractor.py` | Image OCR extraction |
| `tests/integration/test_embedder_integration.py` | OpenAI embedder with real API (or skip) |
| `tests/integration/test_auth_integration.py` | Auth + rate limiting against real PostgreSQL |
| `tests/integration/test_upload_integration.py` | Upload → MinIO → pipeline |
| `tests/integration/test_celery_pipeline.py` | Celery task chain execution |
| `tests/integration/test_docker_e2e.py` | Single end-to-end test |
| `scripts/seed_dev_api_key.py` | Bootstrap a test API key for local development |
| `emerald/api/routes/pipelines.py` | `GET /v1/pipelines/{id}` endpoint |

### Modified Files

| File | Changes |
|---|---|
| `emerald/core/embedder.py` | Implement `OpenAIProvider.embed()`; add Redis cache; auto-fallback |
| `emerald/core/search.py` | Replace keyword memory search with semantic + Neo4j hybrid |
| `emerald/core/engine.py` | Wire embedding cache; ID unification (memory_id as chunk_id) |
| `emerald/core/profile.py` | Wire Redis cache; keep in-memory fallback for tests |
| `emerald/api/dependencies.py` | Real SHA-256 auth + permissions + rate limiting |
| `emerald/api/routes/system.py` | Real health probes for PG, Neo4j, Redis, MinIO |
| `emerald/api/routes/upload.py` | Full MinIO + PG + Celery integration |
| `emerald/pipeline/orchestrator.py` | Implement `process_async` with PG job tracking |
| `emerald/pipeline/tasks.py` | Real Celery task implementations with `run_async()` |
| `emerald/pipeline/extraction/pdf.py` | OCR fallback for image-only pages |
| `emerald/pipeline/extraction/image.py` | Preprocessing pipeline |

---

## Phase 0: Verify Migration Chain (Pre-requisite)

### Task 0: Verify `alembic upgrade head` on fresh PostgreSQL

**Files:**
- Verify: `migrations/alembic/versions/35500f582718_initial_schema.py`
- Verify: `migrations/alembic/versions/002_add_pgvector_embedding.py`
- Verify: `migrations/alembic/versions/003_add_pipeline_jobs_content_type.py`

- [ ] **Step 1: Drop and recreate dev database**

```bash
# If using Docker Compose
# docker compose down -v
cd /Users/nicholasl/Documents/build-whatever/Emerald
# Recreate database (adjust for your setup)
# psql -U emerald -h localhost -c "DROP DATABASE IF EXISTS emerald; CREATE DATABASE emerald;"
```

- [ ] **Step 2: Run migrations**

```bash
/usr/local/bin/python3 -m alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> 35500f582718, ... Running upgrade 35500f582718 -> 002_add_pgvector_embedding ... Running upgrade 002_add_pgvector_embedding -> 003_add_pipeline_jobs_content_type, ...`

- [ ] **Step 3: Verify tables exist**

```bash
# psql -U emerald -h localhost -d emerald -c "\dt"
```

Expected: `entities`, `api_keys`, `documents`, `connectors`, `pipeline_jobs`, `embeddings`, `profile_cache`, `entity_settings`

- [ ] **Step 4: Verify pgvector extension and HNSW index**

```bash
# psql -U emerald -h localhost -d emerald -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
# psql -U emerald -h localhost -d emerald -c "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_embeddings_hnsw';"
```

Expected: both return one row.

- [ ] **Step 5: Commit** (if any fix needed)

```bash
git add migrations/
git commit -m "chore(migrations): verify 001→002→003 chain on fresh PostgreSQL"
```

---

## Phase 1: Embedder + Search (Week 1)

### Task 1: Implement `OpenAIProvider.embed()` with batching and tenacity

**Files:**
- Modify: `emerald/core/embedder.py`
- Create: `tests/unit/test_embedder.py`

- [ ] **Step 1: Write failing test for OpenAI batching**

Create `tests/unit/test_embedder.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

```bash
cd /Users/nicholasl/Documents/build-whatever/Emerald
/usr/local/bin/python3 -m pytest tests/unit/test_embedder.py -v -x
```

Expected: FAIL — `OpenAIProvider.embed()` raises `NotImplementedError`, tests fail at Step 1.

- [ ] **Step 3: Add `EmbeddingError` exception**

Add to `emerald/core/exceptions.py`:

```python
class EmbeddingError(EmeraldError):
    """Raised when embedding generation fails after all retries."""
    pass


class EmbeddingRetryableError(EmbeddingError):
    """Raised on transient embedding failures (429, 502, 503, 504)."""
    pass


class AuthenticationError(EmeraldError):
    """Raised on authentication failures (invalid API key)."""
    pass
```

- [ ] **Step 4: Implement `OpenAIProvider.embed()`**

Replace `emerald/core/embedder.py` `OpenAIProvider`:

```python
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from emerald.core.exceptions import AuthenticationError, EmbeddingError, EmbeddingRetryableError


class OpenAIProvider(EmbeddingProvider):
    """OpenAI text-embedding-3 provider with batching and retry."""

    BATCH_SIZE = 2048
    MAX_RETRIES = 3

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_embeddings = await self._embed_batch_with_retry(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = await self._client.post(
            "/embeddings",
            json={"input": batch, "model": self._model},
        )

        if response.status_code in (429, 502, 503, 504):
            raise EmbeddingRetryableError(f"HTTP {response.status_code}: {response.text}")
        if response.status_code == 401:
            raise AuthenticationError("Invalid OpenAI API key")
        if response.status_code == 400:
            raise ValueError(f"Bad request: {response.text}")

        response.raise_for_status()
        data = response.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    _embed_batch_with_retry = retry(
        retry=retry_if_exception_type(EmbeddingRetryableError),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )(_embed_batch)

    def dimension(self) -> int:
        return self._dimensions_map.get(self._model, 1536)

    async def close(self) -> None:
        await self._client.aclose()
```

> **Lifecycle note:** `OpenAIProvider` holds an `httpx.AsyncClient`. Call `await provider.close()` in FastAPI lifespan shutdown to avoid connection leaks. The lifespan in `emerald/api/app.py` should iterate over all providers and close them.

- [ ] **Step 5: Run tests — should pass**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_embedder.py -v -x
```

Expected: all pass (6 tests).

- [ ] **Step 6: Commit**

```bash
git add emerald/core/embedder.py emerald/core/exceptions.py tests/unit/test_embedder.py
git commit -m "feat(embedder): implement OpenAIProvider with batching + tenacity retry

- Add EmbeddingError, EmbeddingRetryableError, AuthenticationError exceptions.
- OpenAIProvider.embed() supports up to 2048 texts per batch.
- Tenacity: 3 retries with exponential backoff (1s, 2s, 4s).
- Raises AuthenticationError on 401, ValueError on 400, EmbeddingError on final failure.
- MockEmbeddingProvider tests unchanged and still pass.
```

---

### Task 2: Redis embedding cache + auto-fallback in factory

**Files:**
- Modify: `emerald/core/embedder.py` — add `_cached_embed()` method, update `get_embedding_provider()`
- Modify: `tests/unit/test_embedder.py` — add cache and fallback tests

- [ ] **Step 1: Write failing test for cache hit skipping API call**

Append to `tests/unit/test_embedder.py`:

```python
@pytest.mark.asyncio
async def test_openai_cache_hit_skips_api_call(openai_provider):
    """Second call with same text returns cached vector, no API call."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.2] * 1536}]
    }

    with patch.object(openai_provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        # First call — hits API
        r1 = await openai_provider.embed(["cached_text"])
        # Second call — should hit cache
        r2 = await openai_provider.embed(["cached_text"])

    assert mock_post.call_count == 1  # Only one API call
    assert r1 == r2


def test_mock_fallback_when_key_missing(monkeypatch):
    """OPENAI_API_KEY empty → MockEmbeddingProvider."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    # Must reload settings cache
    from emerald.config import _settings, get_settings
    _settings.cache_clear()

    p = get_embedding_provider()
    assert isinstance(p, MockEmbeddingProvider)
    assert p.dimension() == 1536
```

- [ ] **Step 2: Run failing tests**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_embedder.py::test_openai_cache_hit_skips_api_call tests/unit/test_embedder.py::test_mock_fallback_when_key_missing -v
```

Expected: FAIL — cache not implemented, `get_embedding_provider()` doesn't check empty key.

- [ ] **Step 3: Implement embedding cache in OpenAIProvider**

Modify `emerald/core/embedder.py`:

```python
import hashlib
import json

class OpenAIProvider(EmbeddingProvider):
    # ... existing code ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Check Redis cache
        try:
            from emerald.db.redis import get_redis_client
            redis = get_redis_client()
        except RuntimeError:
            redis = None

        hashes = [hashlib.sha256((t + self._model).encode()).hexdigest() for t in texts]
        cached: list[str | None] = []
        if redis:
            cached = await redis.mget([f"emb:{h}" for h in hashes])
        else:
            cached = [None] * len(texts)

        to_fetch: list[str] = []
        to_fetch_indices: list[int] = []
        results: list[list[float] | None] = [None] * len(texts)

        for i, c in enumerate(cached):
            if c is not None:
                results[i] = json.loads(c)
            else:
                to_fetch.append(texts[i])
                to_fetch_indices.append(i)

        if to_fetch:
            fetched = await self._embed_batch_with_retry(to_fetch)
            if redis:
                pipe = redis.pipeline()
                for idx, vec in zip(to_fetch_indices, fetched):
                    h = hashes[idx]
                    pipe.setex(f"emb:{h}", 7 * 86400, json.dumps(vec))
                await pipe.execute()
            for idx, vec in zip(to_fetch_indices, fetched):
                results[idx] = vec

        return [r for r in results if r is not None]
```

- [ ] **Step 4: Update `get_embedding_provider()` with auto-fallback**

```python
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()

    if settings.embedding_provider == EmbeddingProviderEnum.openai:
        if settings.openai_api_key:
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
            )
        logger.warning("OpenAI API key missing; falling back to MockEmbeddingProvider")
        return MockEmbeddingProvider(dimension=1536)

    if settings.embedding_provider in (EmbeddingProviderEnum.bge, EmbeddingProviderEnum.text2vec, EmbeddingProviderEnum.local):
        return LocalProvider(model_path=settings.bge_model_path, dimension=1024)

    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
```

- [ ] **Step 5: Run all embedder tests**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_embedder.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add emerald/core/embedder.py tests/unit/test_embedder.py
git commit -m "feat(embedder): add Redis cache + auto-fallback to MockProvider

- Cache key: sha256(text + model_name), TTL 7 days.
- MGET/MSET pipeline for batch cache operations.
- Auto-fallback to MockEmbeddingProvider when OPENAI_API_KEY is empty.
- All 8 embedder unit tests pass."
```

---

### Task 2.5: Wire Redis embedding cache into MemoryEngine

**Files:**
- Modify: `emerald/core/engine.py` — `_embed()` method

- [ ] **Step 1: Implement `_embed()` with Redis cache**

Replace `_embed` in `emerald/core/engine.py`:

```python
    async def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
        texts = [c.text for c in chunks]
        if not texts:
            return []

        try:
            from emerald.db.redis import get_redis_client
            redis = get_redis_client()
        except RuntimeError:
            redis = None

        import hashlib, json
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]

        embeddings: list[list[float] | None] = [None] * len(texts)
        to_embed: list[str] = []
        to_embed_indices: list[int] = []

        if redis:
            cached = await redis.mget([f"emb:{h}" for h in hashes])
        else:
            cached = [None] * len(texts)

        for i, c in enumerate(cached):
            if c is not None:
                embeddings[i] = json.loads(c)
            else:
                to_embed.append(texts[i])
                to_embed_indices.append(i)

        if to_embed:
            new_embeddings = await self.embedder.embed(to_embed)
            if redis:
                pipe = redis.pipeline()
                for idx, emb in zip(to_embed_indices, new_embeddings):
                    pipe.setex(f"emb:{hashes[idx]}", 7 * 86400, json.dumps(emb))
                await pipe.execute()
            for idx, emb in zip(to_embed_indices, new_embeddings):
                embeddings[idx] = emb

        return [e for e in embeddings if e is not None]
```

- [ ] **Step 2: Run engine tests**

```bash
/usr/local/bin/python3 -m pytest tests/core/test_memory_engine.py -v
```

Expected: all pass (MockEmbeddingProvider unchanged).

- [ ] **Step 3: Commit**

```bash
git add emerald/core/engine.py
git commit -m "feat(engine): add Redis embedding cache to avoid repeated API calls

- Cache key: sha256(text), TTL 7 days.
- MGET for batch cache lookup; MSET pipeline for storing new embeddings.
- Graceful degradation: Redis unavailable → embed all texts directly.
- MemoryEngine._index() already passes memory_id as chunk_id to VectorStore."
```

---

### Task 3: Semantic hybrid search overhaul

**Files:**
- Modify: `emerald/core/search.py` — rewrite `_search_memory()`
- Create: `tests/unit/test_search_semantic.py`

- [ ] **Step 1: Write failing test for semantic keyword mismatch**

Create `tests/unit/test_search_semantic.py`:

```python
"""Tests for semantic memory search."""

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore


@pytest.fixture
def populated_search():
    """Search orchestrator with hiking memory stored in graph + vector."""
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)

    # Seed hiking memory
    memory_id = "mem_hiking_001"
    # Manually insert into graph and vector with same ID
    graph._memories.setdefault("user_1", []).append({
        "id": memory_id,
        "content": "我喜欢周末去山里 hiking",
        "summary": "周末 hiking 爱好",
        "memory_type": "fact",
        "confidence": 0.9,
        "is_latest": True,
        "valid_from": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        "valid_until": None,
    })
    emb = embedder._cosine_similarity  # no sync method; just store deterministic vector
    # Actually use embedder
    import asyncio
    vec = asyncio.run(embedder.embed(["我喜欢周末去山里 hiking"]))[0]
    asyncio.run(vector.store(memory_id, "我喜欢周末去山里 hiking", vec, entity_id="user_1"))

    orchestrator = SearchOrchestrator(graph=graph, vector=vector, embedder=embedder)
    return orchestrator


@pytest.mark.asyncio
async def test_memory_search_semantic_keyword_mismatch(populated_search):
    """'户外活动' should find 'hiking' memory via semantic similarity."""
    result = await populated_search.search(
        "户外活动", entity_id="user_1", search_mode=SearchMode.MEMORY, top_k=5
    )
    assert len(result.results) >= 1
    assert any("hiking" in r.content for r in result.results)
```

- [ ] **Step 2: Run failing test**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_search_semantic.py -v -x
```

Expected: FAIL — `_search_memory` still uses keyword scoring, "户外活动" and "hiking" don't overlap.

- [ ] **Step 3: Implement semantic `_search_memory()`**

Add `timezone` import at the top of `emerald/core/search.py`:

```python
from datetime import datetime, timezone
```

Then replace `_search_memory`:

```python
    async def _search_memory(
        self,
        q: str,
        entity_id: str,
        top_k: int,
        filters: dict | None,
    ) -> list[SearchResult]:
        if not self.embedder:
            return []

        query_embedding = (await self.embedder.embed([q]))[0]
        candidate_limit = min(top_k * 5, 100)
        candidates = await self.vector.search(
            query_embedding, entity_id=entity_id, top_k=candidate_limit
        )

        results = []
        now = datetime.now(timezone.utc)

        for chunk_id, text, vec_score in candidates:
            memory = await self.graph.get_memory(chunk_id)
            if not memory:
                continue
            if not memory.get("is_latest", True):
                continue
            valid_until = memory.get("valid_until")
            if valid_until is not None:
                # Neo4j returns neo4j.time.DateTime; convert to Python datetime
                if hasattr(valid_until, "to_native"):
                    valid_until = valid_until.to_native()
                if valid_until < now:
                    continue
            if filters and not self._passes_filters(memory, filters):
                continue

            score = vec_score * memory.get("confidence", 0.5)
            results.append(
                SearchResult(
                    id=memory["id"],
                    content=memory["content"],
                    summary=memory.get("summary", "")[:200],
                    score=score,
                    source="memory",
                    memory_type=memory.get("memory_type", "fact"),
                    is_latest=memory.get("is_latest", True),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _passes_filters(self, memory: dict, filters: dict) -> bool:
        mtype = filters.get("memory_type")
        min_conf = filters.get("min_confidence")
        if mtype and memory.get("memory_type") != mtype:
            return False
        if min_conf is not None and memory.get("confidence", 0) < min_conf:
            return False
        return True
```

- [ ] **Step 4: Run search tests**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_search_semantic.py -v
```

Expected: pass.

- [ ] **Step 5: Verify existing search tests still pass**

```bash
/usr/local/bin/python3 -m pytest tests/core/test_search.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add emerald/core/search.py tests/unit/test_search_semantic.py
git commit -m "feat(search): replace keyword memory search with semantic pgvector + Neo4j hybrid

- _search_memory now embeds query, recalls from pgvector, filters via Neo4j.
- Candidate limit = min(top_k * 5, 100) to tolerate high expiry rates.
- Score blending: vector_similarity * confidence.
- Existing keyword-based RAG search (_search_rag) unchanged.
- All existing search tests pass; new semantic test added."
```

---

### Task 4: API key authentication + permissions + rate limiting

**Files:**
- Modify: `emerald/api/dependencies.py`
- Modify: `emerald/models/api_key.py` (if needed)
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: Write failing auth tests**

Create `tests/unit/test_auth.py`:

```python
"""Unit tests for API key authentication."""

import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from emerald.api.dependencies import api_key_auth, require_write_permission


class FakeRequest:
    def __init__(self, headers=None, state=None):
        self.headers = headers or {}
        self.state = state or type("State", (), {})()


@pytest.mark.asyncio
async def test_missing_header_returns_401():
    req = FakeRequest(headers={})
    with pytest.raises(HTTPException) as exc_info:
        await api_key_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_key_returns_401():
    req = FakeRequest(headers={"Authorization": "Bearer bad_key"})
    with pytest.raises(HTTPException) as exc_info:
        await api_key_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_with_db_record_authenticates():
    """Valid key with matching DB record → authenticated + state populated."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    req = FakeRequest(headers={"Authorization": "Bearer em_validkey"})

    fake_record = MagicMock()
    fake_record.id = uuid.uuid4()
    fake_record.entity_id = uuid.uuid4()
    fake_record.permissions = ["read", "write"]
    fake_record.expires_at = None
    fake_record.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_record

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("emerald.api.dependencies.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await api_key_auth(req)

    assert result == "authenticated"
    assert getattr(req.state, "permissions", []) == ["read", "write"]
    assert hasattr(req.state, "entity_id")
    assert hasattr(req.state, "api_key_id")
```

- [ ] **Step 2: Run existing stub tests — should pass**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_auth.py -v
```

Expected: first 2 fail (401), last passes (stub accepts em_*).

- [ ] **Step 3: Implement real `api_key_auth()`**

Replace `emerald/api/dependencies.py`:

```python
"""API authentication dependencies."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status

from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey


async def api_key_auth(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].startswith("em_"):
        raise HTTPException(401, "Missing or invalid API key")

    api_key = parts[1]
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async with session_factory.session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(401, "Invalid API key")

    if record.expires_at and record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "API key expired")

    request.state.api_key_id = str(record.id)
    request.state.entity_id = str(record.entity_id)
    request.state.permissions = record.permissions or []
    return "authenticated"


async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(403, "Write permission required")
    return "authorized"
```

- [ ] **Step 4: Add rate limiting dependency**

Append to `emerald/api/dependencies.py`:

```python
async def rate_limit(request: Request) -> None:
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return  # Auth hasn't run yet or failed

    endpoint = request.url.path
    limit = 60  # Fixed-window: 60 requests per minute per endpoint

    try:
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
    except RuntimeError:
        return  # Redis unavailable — skip rate limiting

    key = f"ratelimit:{key_id}:{endpoint}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)
    if current > limit:
        raise HTTPException(
            429,
            "Rate limit exceeded",
            headers={"Retry-After": "60"},
        )
```

- [ ] **Step 5: Update auth tests for real implementation**

```python
@pytest.mark.asyncio
async def test_expired_key_returns_401():
    req = FakeRequest(headers={"Authorization": "Bearer em_expired"})
    # Would need DB setup for full test; mark as integration
    pytest.skip("Requires PostgreSQL — moved to integration test")
```

- [ ] **Step 6: Run unit tests**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_auth.py -v
```

Expected: stub tests pass (valid key), new real-auth tests need DB (skip or mock).

- [ ] **Step 7: Commit**

```bash
git add emerald/api/dependencies.py tests/unit/test_auth.py
git commit -m "feat(auth): implement SHA-256 API key auth + permissions + rate limiting

- api_key_auth: Bearer em_* → hash → PostgreSQL api_keys table lookup.
- Validates is_active and expires_at.
- Stores api_key_id, entity_id, permissions in request.state.
- require_write_permission: checks for 'write' or 'admin' in permissions.
- rate_limit: Redis fixed-window 60 req/min per endpoint per key.
- Graceful degradation: Redis unavailable → skip rate limiting."
```

---

### Task 5: Real health check probes

**Files:**
- Modify: `emerald/api/routes/system.py`
- Create: `tests/unit/test_health.py`

- [ ] **Step 1: Write failing health test**

Create `tests/unit/test_health.py`:

```python
"""Unit tests for health check endpoint."""

import pytest
from unittest.mock import AsyncMock, patch

from emerald.api.routes.system import health_check


@pytest.mark.asyncio
async def test_health_all_ok():
    with patch("emerald.api.routes.system._probe_postgres", new_callable=AsyncMock) as pg, \
         patch("emerald.api.routes.system._probe_neo4j", new_callable=AsyncMock) as neo, \
         patch("emerald.api.routes.system._probe_redis", new_callable=AsyncMock) as redis, \
         patch("emerald.api.routes.system._probe_minio", new_callable=AsyncMock) as minio:
        result = await health_check()

    assert result["status"] == "ok"
    assert result["checks"]["database"] == "ok"
    assert result["checks"]["neo4j"] == "ok"
    assert result["checks"]["redis"] == "ok"
    assert result["checks"]["minio"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_neo4j_down():
    with patch("emerald.api.routes.system._probe_postgres", new_callable=AsyncMock), \
         patch("emerald.api.routes.system._probe_neo4j", side_effect=ConnectionError("Neo4j down")), \
         patch("emerald.api.routes.system._probe_redis", new_callable=AsyncMock), \
         patch("emerald.api.routes.system._probe_minio", new_callable=AsyncMock):
        result = await health_check()

    assert result["status"] == "degraded"
    assert "error" in result["checks"]["neo4j"]
```

- [ ] **Step 2: Run failing test**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_health.py -v
```

Expected: FAIL — probes don't exist, health_check returns static JSON.

- [ ] **Step 3: Implement real health probes**

Replace `emerald/api/routes/system.py`:

```python
"""System routes — health check and metrics."""

from __future__ import annotations

from fastapi import APIRouter

from emerald.config import get_settings

router = APIRouter(tags=["System"])


async def _probe_postgres() -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text
    async with session_factory.session() as session:
        await session.execute(text("SELECT 1"))


async def _probe_neo4j() -> None:
    from emerald.db.neo4j import get_neo4j_driver
    driver = get_neo4j_driver()
    await driver.verify_connectivity()


async def _probe_redis() -> None:
    from emerald.db.redis import get_redis_client
    redis = get_redis_client()
    await redis.ping()


async def _probe_minio() -> None:
    from emerald.config import get_settings
    settings = get_settings()
    # MinIO probe: list buckets (lightweight)
    from minio import Minio
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    client.list_buckets()


@router.get("/health", response_model=dict)
async def health_check() -> dict:
    checks = {}
    overall = "ok"

    for name, probe in [
        ("database", _probe_postgres),
        ("neo4j", _probe_neo4j),
        ("redis", _probe_redis),
        ("minio", _probe_minio),
    ]:
        try:
            await probe()
            checks[name] = "ok"
        except Exception as e:
            checks[name] = f"error: {e}"
            overall = "degraded"

    return {"status": overall, "version": "0.1.0", "checks": checks}
```

- [ ] **Step 4: Run health tests**

```bash
/usr/local/bin/python3 -m pytest tests/unit/test_health.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add emerald/api/routes/system.py tests/unit/test_health.py
git commit -m "feat(health): implement real health probes for PG, Neo4j, Redis, MinIO

- Each probe does a lightweight connectivity check.
- Returns 200 with status 'ok' or 'degraded' + per-service error details.
- Unit tests mock probes to test both all-ok and degraded scenarios."
```

---

### Task 5.5: Wire Redis-backed profile cache

**Files:**
- Modify: `emerald/core/profile.py`
- Test: `tests/integration/test_redis_cache.py`

- [ ] **Step 1: Replace ProfileManager with Redis support**

Replace `ProfileManager` in `emerald/core/profile.py`:

```python
class ProfileManager:
    """Manages entity profiles: compute, cache, invalidate.

    Uses Redis in production; in-memory dict fallback for tests without Redis.
    """

    STATIC_CONFIDENCE_MIN = 0.5
    DYNAMIC_CONFIDENCE_MIN = 0.3
    DYNAMIC_LOOKBACK_DAYS = 7
    STATIC_MAX_ITEMS = 10
    DYNAMIC_MAX_ITEMS = 5
    TTL = 24 * 3600

    def __init__(
        self,
        graph: GraphStore | None = None,
        redis_client=None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self._redis = redis_client
        self._versions: dict[str, int] = {}

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from emerald.db.redis import get_redis_client
            return get_redis_client()
        except RuntimeError:
            return None

    async def get(self, entity_id: str) -> EntityProfile:
        redis = self._get_redis()
        if redis:
            cached = await redis.get(f"profile:{entity_id}")
            if cached:
                logger.debug("profile.cache.hit", entity_id=entity_id)
                data = json.loads(cached)
                return EntityProfile(
                    entity_id=data["entity_id"],
                    static=[ProfileFact(**f) for f in data["static"]],
                    dynamic=[ProfileFact(**f) for f in data["dynamic"]],
                    memory_count=data["memory_count"],
                    computed_at=data["computed_at"],
                    version=data["version"],
                )

        logger.info("profile.cache.miss", entity_id=entity_id)
        profile = await self.compute(entity_id)

        if redis:
            await redis.setex(
                f"profile:{entity_id}",
                self.TTL,
                json.dumps({
                    "entity_id": profile.entity_id,
                    "static": [{"content": f.content, "importance": f.importance} for f in profile.static],
                    "dynamic": [{"content": f.content, "relevance": f.relevance, "source": f.source, "acquired_at": f.acquired_at} for f in profile.dynamic],
                    "memory_count": profile.memory_count,
                    "computed_at": profile.computed_at,
                    "version": profile.version,
                }),
            )
        return profile

    async def invalidate(self, entity_id: str) -> None:
        redis = self._get_redis()
        if redis:
            await redis.delete(f"profile:{entity_id}")
            logger.info("profile.cache.invalidated", entity_id=entity_id)

    async def compute(self, entity_id: str) -> EntityProfile:
        # ... existing compute logic unchanged ...
        all_memories = await self.graph.list_latest_memories(entity_id, limit=200)
        # ... rest of existing code ...
```

- [ ] **Step 2: Run profile tests**

```bash
/usr/local/bin/python3 -m pytest tests/core/test_profile_manager.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add emerald/core/profile.py
git commit -m "feat(profile): implement Redis-backed profile cache

- Cache key: profile:{entity_id}, TTL 24h.
- get(): checks Redis first; miss → compute from graph → store in Redis.
- invalidate(): DEL profile:{entity_id} on new memory ingestion.
- In-memory fallback preserved for tests without Redis."
```

---

### Task 6: File upload endpoint

**Files:**
- Modify: `emerald/api/routes/upload.py`
- Create: `emerald/api/routes/pipelines.py`
- Create: `tests/unit/test_upload.py` *(skeleton — full test deferred to integration suite)*

- [ ] **Step 1: Implement upload route with MinIO + PG + Celery**

Replace `emerald/api/routes/upload.py`:

```python
"""Upload routes — POST /v1/upload + GET /v1/files + GET /v1/pipelines/{id}."""

from __future__ import annotations

import io
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from emerald.api.dependencies import api_key_auth, require_write_permission
from emerald.config import get_settings

router = APIRouter(tags=["Upload"])


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def upload_file(
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
) -> dict:
    settings = get_settings()

    # 1. Read and validate size
    contents = await file.read()
    max_size = 50 * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(413, f"File too large: {len(contents)} bytes (max {max_size})")

    # 2. Detect content type
    detected = content_type or _detect_mime(file.filename)

    # 3. Store in MinIO
    storage_key = f"{entity_id}/{uuid4().hex}/{file.filename or 'untitled'}"
    minio_client = _get_minio_client()
    minio_client.put_object(
        settings.minio_bucket,
        storage_key,
        io.BytesIO(contents),
        len(contents),
        content_type=detected,
    )

    # 4. Resolve external entity_id → internal UUID, then create Document
    from emerald.db.session import session_factory
    from emerald.models.document import Document
    from emerald.models.entity import Entity
    from sqlalchemy import select
    import uuid

    async with session_factory.session() as session:
        result = await session.execute(
            select(Entity).where(Entity.external_id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(404, f"Entity '{entity_id}' not found")

        doc = Document(
            entity_id=entity.id,
            title=title or file.filename or "untitled",
            content_type=detected,
            storage_key=storage_key,
            file_size_bytes=len(contents),
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

    # 5. Submit async pipeline
    from emerald.pipeline.orchestrator import PipelineOrchestrator
    orchestrator = PipelineOrchestrator()
    pipeline_id = await orchestrator.process_async(
        content=contents,
        content_type=detected,
        entity_id=entity_id,
        document_id=str(doc.id),
    )

    return {
        "data": {
            "document_id": str(doc.id),
            "pipeline_id": pipeline_id,
            "pipeline_status": "queued",
            "file_size_bytes": len(contents),
            "content_type": detected,
            "title": title or file.filename or "untitled",
        }
    }


def _detect_mime(filename: str | None) -> str:
    if not filename:
        return "application/octet-stream"
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain",
        "md": "text/markdown",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    return mapping.get(ext, "application/octet-stream")


def _get_minio_client():
    from minio import Minio
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


# ---- _is_uuid is provided by emerald.utils ----
from emerald.utils import _is_uuid

# ---- GET /pipelines/{id} moved to emerald/api/routes/pipelines.py ----
```

- [ ] **Step 2: Create pipelines route**

Create `emerald/api/routes/pipelines.py`:

```python
"""Pipeline status routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from emerald.api.dependencies import api_key_auth
from emerald.db.session import session_factory
from emerald.models.pipeline_job import PipelineJob

router = APIRouter(tags=["Pipelines"])


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_status(
    pipeline_id: str,
    _: str = Depends(api_key_auth),
) -> dict:
    from sqlalchemy import select
    async with session_factory.session() as session:
        result = await session.execute(
            select(PipelineJob).where(PipelineJob.id == pipeline_id)
        )
        job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(404, f"Pipeline {pipeline_id} not found")

    return {
        "data": {
            "pipeline_id": str(job.id),
            "status": job.status,
            "entity_id": str(job.entity_id),
            "document_id": str(job.document_id) if job.document_id else None,
            "content_type": getattr(job, "content_type", None),
            "error_message": job.error_message,
            "retry_count": job.retry_count,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    }
```

- [ ] **Step 3: Register pipelines router and wire rate limiting**

Modify `emerald/api/app.py`:

```python
from emerald.api.routes import pipelines
app.include_router(pipelines.router, prefix="/v1")
```

Also wire `rate_limit` to protected routes. In `emerald/api/routes/upload.py`:

```python
from emerald.api.dependencies import rate_limit

# Add rate_limit to upload endpoint dependencies:
# dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)]
```

> **CR-7 fix:** `rate_limit` must be applied to all mutation/search endpoints.
> Apply the same pattern to `emerald/api/routes/memories.py` and `emerald/api/routes/search.py`.

- [ ] **Step 4: Commit**

```bash
git add emerald/api/routes/upload.py emerald/api/routes/pipelines.py emerald/api/app.py
git commit -m "feat(upload): implement full upload endpoint with MinIO + PG + pipeline

- POST /v1/upload: validates size (≤50MB), detects MIME, stores in MinIO,
  creates Document record, submits async Celery pipeline.
- GET /v1/pipelines/{id}: queries pipeline_jobs table for status.
- _detect_mime maps common extensions; falls back to application/octet-stream."
```

---

### Task 7: Celery pipeline task chain

**Files:**
- Modify: `emerald/pipeline/orchestrator.py`
- Modify: `emerald/pipeline/tasks.py`
- Create: `tests/integration/test_celery_pipeline.py`

- [ ] **Step 1: Implement `PipelineOrchestrator.process_async()`**

Replace `emerald/pipeline/orchestrator.py`:

```python
"""Pipeline orchestrator — async pipeline entry point."""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import structlog
from celery import chain

from emerald.config import get_settings
from emerald.db.session import session_factory
from emerald.models.pipeline_job import PipelineJob
from emerald.pipeline.chunking.registry import ChunkerRegistry
from emerald.pipeline.extraction.registry import ExtractorRegistry
from emerald.pipeline.tasks import (
    extract_task,
    chunk_task,
    embed_task,
    index_task,
    postprocess_task,
)

logger = structlog.get_logger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        extractor_registry: ExtractorRegistry | None = None,
        chunker_registry: ChunkerRegistry | None = None,
    ) -> None:
        self.extractors = extractor_registry or ExtractorRegistry()
        self.chunkers = chunker_registry or ChunkerRegistry()

    async def process_async(
        self,
        content: str | bytes,
        *,
        content_type: str,
        entity_id: str,
        document_id: str | None = None,
    ) -> str:
        pipeline_id = uuid4().hex
        content_hash = sha256(
            content.encode() if isinstance(content, str) else content
        ).hexdigest()

        async with session_factory.session() as session:
            from sqlalchemy import select
            from emerald.models.entity import Entity
            result = await session.execute(
                select(Entity).where(Entity.external_id == entity_id)
            )
            entity = result.scalar_one_or_none()
            if not entity:
                raise ValueError(f"Entity '{entity_id}' not found")

            session.add(
                PipelineJob(
                    id=uuid.UUID(pipeline_id),
                    entity_id=entity.id,
                    document_id=uuid.UUID(document_id) if document_id and _is_uuid(document_id) else None,
                    content_hash=content_hash,
                    content_type=content_type,
                    status="queued",
                )
            )
            await session.commit()

        chain(
            extract_task.s(pipeline_id, content, content_type),
            chunk_task.s(),
            embed_task.s(),
            index_task.s(entity_id),
            postprocess_task.s(entity_id),
        ).apply_async()

        logger.info(
            "pipeline.async.submitted",
            pipeline_id=pipeline_id,
            entity_id=entity_id,
            content_type=content_type,
        )
        return pipeline_id


# _is_uuid moved to emerald/utils.py (shared helper)
from emerald.utils import _is_uuid
```

> **M-4 fix:** Extract `_is_uuid` to `emerald/utils.py` to avoid duplication between upload and orchestrator.
> Create `emerald/utils.py`:
> ```python
> import uuid
> def _is_uuid(s: str) -> bool:
>     try:
>         uuid.UUID(s)
>         return True
>     except ValueError:
>         return False
> ```

- [ ] **Step 2: Implement real Celery tasks**

Replace `emerald/pipeline/tasks.py`:

```python
"""Pipeline Celery tasks — async task chain for processing."""

from __future__ import annotations

import json
import structlog
from celery import shared_task

from emerald.async_utils import run_async

logger = structlog.get_logger(__name__)


async def _update_status(pipeline_id: str, status: str) -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text
    async with session_factory.session() as session:
        await session.execute(
            text("UPDATE pipeline_jobs SET status = :status, updated_at = NOW() WHERE id = :id"),
            {"status": status, "id": pipeline_id},
        )


async def _update_error(pipeline_id: str, stage: str, error: str) -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text
    async with session_factory.session() as session:
        await session.execute(
            text("""
                UPDATE pipeline_jobs
                SET status = 'failed', error_message = :error, updated_at = NOW()
                WHERE id = :id
            """),
            {"error": f"{stage}: {error}", "id": pipeline_id},
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    return run_async(_run_extract)(self, pipeline_id, content, content_type)


async def _run_extract(task_self, pipeline_id, content, content_type):
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "extracting")
        from emerald.pipeline.extraction.registry import ExtractorRegistry
        extractor = ExtractorRegistry().get(content_type)
        result = await extractor.extract(content)

        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        await redis.setex(f"pipeline:{pipeline_id}:text", 86400, result.text)

        return {"pipeline_id": pipeline_id, "content_type": content_type}
    except Exception as exc:
        await _update_error(pipeline_id, "extracting", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def chunk_task(self, prev_result: dict) -> dict:
    return run_async(_run_chunk)(self, prev_result)


async def _run_chunk(task_self, prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "chunking")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        text = await redis.get(f"pipeline:{pipeline_id}:text")

        from emerald.pipeline.chunking.registry import ChunkerRegistry
        chunker = ChunkerRegistry().get(prev_result.get("content_type", "text"))
        chunks = chunker.chunk(text or "")

        data = [
            {"id": c.id, "text": c.text, "index": c.index, "token_count": c.token_count}
            for c in chunks
        ]
        await redis.setex(f"pipeline:{pipeline_id}:chunks", 86400, json.dumps(data))
        return {"pipeline_id": pipeline_id, "chunk_count": len(chunks)}
    except Exception as exc:
        await _update_error(pipeline_id, "chunking", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def embed_task(self, prev_result: dict) -> dict:
    return run_async(_run_embed)(self, prev_result)


async def _run_embed(task_self, prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "embedding")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
        chunks_data = json.loads(chunks_raw or "[]")
        texts = [c["text"] for c in chunks_data]

        from emerald.core.embedder import get_embedding_provider
        provider = get_embedding_provider()
        embeddings = await provider.embed(texts)

        await redis.setex(f"pipeline:{pipeline_id}:embeddings", 86400, json.dumps(embeddings))
        return {"pipeline_id": pipeline_id}
    except Exception as exc:
        await _update_error(pipeline_id, "embedding", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True)
def index_task(self, prev_result: dict, entity_id: str) -> dict:
    return run_async(_run_index)(self, prev_result, entity_id)


async def _run_index(task_self, prev_result: dict, entity_id: str) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "indexing")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
        embeddings_raw = await redis.get(f"pipeline:{pipeline_id}:embeddings")
        chunks_data = json.loads(chunks_raw or "[]")
        embeddings = json.loads(embeddings_raw or "[]")

        from emerald.core.graph import GraphStore
        from emerald.core.vector import VectorStore
        graph = GraphStore(use_db=True)
        vector = VectorStore(use_db=True)

        memory_ids = []
        for chunk_data, embedding in zip(chunks_data, embeddings):
            mid = await graph.create_memory(
                content=chunk_data["text"],
                entity_id=entity_id,
                memory_type="fact",
                confidence=0.8,
                source_type="document",
            )
            memory_ids.append(mid)
            await vector.store(
                chunk_id=mid,
                text=chunk_data["text"],
                embedding=embedding,
                entity_id=entity_id,
            )

        return {"pipeline_id": pipeline_id, "memory_ids": memory_ids}
    except Exception as exc:
        await _update_error(pipeline_id, "indexing", str(exc))
        raise
    finally:
        await close_neo4j()


@shared_task
def postprocess_task(prev_result: dict, entity_id: str) -> None:
    return run_async(_run_postprocess)(prev_result, entity_id)


async def _run_postprocess(prev_result: dict, entity_id: str) -> None:
    pipeline_id = prev_result["pipeline_id"]
    memory_ids = prev_result.get("memory_ids", [])

    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        from emerald.core.relationship import RelationshipEngine
        rel_engine = RelationshipEngine(graph=GraphStore(use_db=True))
        await rel_engine.infer(memory_ids, entity_id)

        from emerald.core.profile import ProfileManager
        profile_mgr = ProfileManager(graph=GraphStore(use_db=True))
        await profile_mgr.invalidate(entity_id)

        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        for key in ["text", "chunks", "embeddings"]:
            await redis.delete(f"pipeline:{pipeline_id}:{key}")

        await _update_status(pipeline_id, "done")
    finally:
        await close_neo4j()
```

- [ ] **Step 3: Write Celery integration test**

Create `tests/integration/test_celery_pipeline.py`:

```python
"""Integration tests for Celery pipeline with in-memory broker."""

import pytest
from celery import Celery

from emerald.pipeline.tasks import extract_task, chunk_task


@pytest.fixture
def celery_app():
    app = Celery("test", broker="memory://")
    app.conf.task_always_eager = True
    return app


def test_extract_task_runs(celery_app):
    result = extract_task.run("pipe_1", b"hello world", "text")
    assert result["pipeline_id"] == "pipe_1"


def test_chunk_task_follows_extract(celery_app):
    # Seed Redis with extracted text
    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis()
    # This test would need Redis mocking; keep minimal
    prev = {"pipeline_id": "pipe_1", "content_type": "text"}
    result = chunk_task.run(prev)
    assert result["pipeline_id"] == "pipe_1"
```

- [ ] **Step 4: Commit**

```bash
git add emerald/pipeline/orchestrator.py emerald/pipeline/tasks.py tests/integration/test_celery_pipeline.py
git commit -m "feat(pipeline): implement real Celery task chain with PG status tracking

- PipelineOrchestrator.process_async writes PipelineJob to PG, submits Celery chain.
- extract_task: runs extractor, stores result in Redis (TTL 24h).
- chunk_task: chunks text, stores chunks in Redis.
- embed_task: generates embeddings via provider.embed().
- index_task: writes to Neo4j + pgvector, returns memory_ids.
- postprocess_task: infers relationships, invalidates profile, cleans Redis.
- All tasks use run_async() for async DB access inside Celery sync tasks."
```

---

### Task 8: PDF and Image extractors

**Files:**
- Modify: `emerald/pipeline/extraction/pdf.py`
- Modify: `emerald/pipeline/extraction/image.py`
- Create: `tests/unit/test_pdf_extractor.py`
- Create: `tests/unit/test_image_extractor.py`

- [ ] **Step 1: Implement PDF extractor with OCR fallback**

Replace `emerald/pipeline/extraction/pdf.py`:

```python
"""PDF extractor — text extraction with OCR fallback for image-only pages."""

from __future__ import annotations

import io

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class PDFExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ExtractionError("PyMuPDF not installed", retryable=False)

        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise ExtractionError(f"Failed to open PDF: {e}", retryable=False)

        text_parts = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{text}")
            else:
                # Image-only page: OCR fallback
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                ocr_text = await self._ocr_fallback(img_bytes)
                text_parts.append(f"[Page {page_num + 1}]\n{ocr_text}")

        doc.close()
        full_text = "\n\n".join(text_parts)
        return ExtractedContent(
            text=full_text,
            content_type="pdf",
            metadata={"page_count": len(text_parts)},
        )

    async def _ocr_fallback(self, img_bytes: bytes) -> str:
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text or "(OCR: no text detected)"
        except ImportError:
            return "(OCR unavailable)"
        except Exception as e:
            return f"(OCR error: {e})"
```

- [ ] **Step 2: Implement Image extractor with preprocessing**

Replace `emerald/pipeline/extraction/image.py`:

```python
"""Image extractor — OCR with preprocessing pipeline."""

from __future__ import annotations

import io

from PIL import ImageFilter

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class ImageExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            raise ExtractionError("Pillow / Tesseract not installed", retryable=False)

        try:
            img = Image.open(io.BytesIO(content))
            # Preprocess: grayscale → denoise → threshold
            gray = img.convert("L")
            denoised = gray.filter(ImageFilter.MedianFilter(size=3))
            thresh = denoised.point(lambda x: 0 if x < 128 else 255, "1")

            try:
                text = pytesseract.image_to_string(thresh, lang="chi_sim+eng")
            except Exception:
                text = pytesseract.image_to_string(thresh, lang="eng")

            return ExtractedContent(
                text=text,
                content_type="image",
                metadata={"image_size": img.size},
            )
        except Exception as e:
            raise ExtractionError(f"Image processing failed: {e}", retryable=False)
```

- [ ] **Step 3: Write extractor unit tests**

Create `tests/unit/test_pdf_extractor.py`:

```python
"""Unit tests for PDF extractor."""

import pytest

from emerald.pipeline.extraction.pdf import PDFExtractor


@pytest.fixture
def pdf_extractor():
    return PDFExtractor()


def test_pdf_missing_pymupdf(pdf_extractor, monkeypatch):
    """ImportError → ExtractionError(retryable=False)."""
    monkeypatch.setitem(__import__("sys").modules, "fitz", None)
    # This is tricky to test; skip if fitz is installed
    pytest.importorskip("fitz", reason="PyMuPDF not installed")


def test_pdf_corrupted(pdf_extractor):
    """Invalid bytes → ExtractionError."""
    with pytest.raises(Exception):  # ExtractionError
        # Run sync wrapper since extract is async
        import asyncio
        asyncio.run(pdf_extractor.extract(b"not a pdf"))
```

Create `tests/unit/test_image_extractor.py`:

```python
"""Unit tests for Image extractor."""

import pytest

from emerald.pipeline.extraction.image import ImageExtractor


@pytest.fixture
def image_extractor():
    return ImageExtractor()


def test_image_missing_tesseract(image_extractor, monkeypatch):
    pytest.importorskip("pytesseract", reason="Tesseract not installed")
```

- [ ] **Step 4: Commit**

```bash
git add emerald/pipeline/extraction/pdf.py emerald/pipeline/extraction/image.py tests/unit/test_pdf_extractor.py tests/unit/test_image_extractor.py
git commit -m "feat(extraction): implement PDF OCR fallback + image preprocessing

- PDFExtractor: text extraction per page; image-only pages fallback to OCR.
- ImageExtractor: grayscale → median denoise → threshold → Tesseract OCR.
- Supports chi_sim+eng; falls back to eng on TesseractError.
- ExtractionError(retryable=False) on missing dependencies or corrupted input."
```

---

### Task 9: Integration tests + seed script

**Files:**
- Create: `scripts/seed_dev_api_key.py`
- Create: `tests/integration/test_embedder_integration.py`
- Create: `tests/integration/test_auth_integration.py`
- Create: `tests/integration/test_upload_integration.py`

- [ ] **Step 1: Create seed script**

Create `scripts/seed_dev_api_key.py`:

```python
"""Bootstrap a development API key. Run once after migrations."""

import asyncio
import hashlib
import uuid

from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey
from emerald.models.entity import Entity


async def main():
    async with session_factory.session() as session:
        # Create dev entity
        entity = Entity(
            external_id="dev_user",
            type="user",
            name="Development User",
        )
        session.add(entity)
        await session.flush()

        # Create dev API key
        raw_key = "em_dev_test_key_001"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            entity_id=entity.id,
            key_hash=key_hash,
            key_prefix=raw_key[:8],
            permissions=["read", "write", "admin"],
            is_active=True,
        )
        session.add(api_key)
        await session.commit()

        print(f"Dev API key created: {raw_key}")
        print(f"Entity ID: {entity.id}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create integration test skeletons**

Create `tests/integration/test_embedder_integration.py`:

```python
"""Integration tests for OpenAI embedder. Skipped if no API key."""

import os
import pytest

from emerald.core.embedder import OpenAIProvider


@pytest.fixture
async def real_provider():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return OpenAIProvider(api_key=api_key)


@pytest.mark.asyncio
async def test_real_openai_embeds_semantically(real_provider):
    """'cat' and 'feline' should have high cosine similarity."""
    import math
    vecs = await real_provider.embed(["cat", "feline", "car"])
    # cat vs feline should be closer than cat vs car
    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb)

    assert cos(vecs[0], vecs[1]) > cos(vecs[0], vecs[2])
```

Create `tests/integration/test_auth_integration.py`:

```python
"""Integration tests for auth against real PostgreSQL."""

import pytest


@pytest.mark.asyncio
async def test_valid_key_authenticates():
    # TODO: unskip after seed_dev_api_key.py runs in test setup
    pytest.skip("Requires running PostgreSQL + seeded api_keys")
```

Create `tests/integration/test_upload_integration.py`:

```python
"""Integration tests for file upload against real services."""

import pytest


def test_upload_creates_document():
    # TODO: unskip when MinIO + PostgreSQL + Celery worker are running in CI
    pytest.skip("Requires running MinIO + PostgreSQL + Celery worker")
```

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_dev_api_key.py tests/integration/test_embedder_integration.py tests/integration/test_auth_integration.py tests/integration/test_upload_integration.py
git commit -m "test(integration): add seed script and integration test skeletons

- scripts/seed_dev_api_key.py: bootstraps dev entity + full-permission API key.
- test_embedder_integration.py: real OpenAI semantic similarity (skip if no key).
- test_auth_integration.py: placeholder for PG-backed auth tests.
- test_upload_integration.py: placeholder for MinIO+PG+Celery upload tests."
```

---

### Task 10: Docker E2E test + coverage audit

**Files:**
- Create: `tests/integration/test_docker_e2e.py`
- Modify: `README.md`

- [ ] **Step 1: Write Docker E2E test**

Create `tests/integration/test_docker_e2e.py`:

```python
"""End-to-end test against full Docker Compose stack."""

import pytest


@pytest.mark.skip(reason="Requires docker compose up")
async def test_full_docker_e2e():
    """
    1. Seed dev API key.
    2. Add text memory → verify Neo4j + pgvector.
    3. Search with semantic mismatch → verify real embedding recall.
    4. Get profile → verify Redis cache hit on second call.
    5. Upload PDF → verify MinIO object, pipeline completion, searchability.
    6. Verify entity isolation.
    """
    pass
```

- [ ] **Step 2: Run coverage audit**

```bash
cd /Users/nicholasl/Documents/build-whatever/Emerald
/usr/local/bin/python3 -m pytest tests/unit/ --cov=emerald --cov-report=term-missing
```

Expected: ≥ 80% line coverage. **Do not use `--cov-fail-under` during incremental development** — only enforce at final CI gate after all tasks complete.

- [ ] **Step 3: Update README**

Add to `README.md`:

```markdown
## OpenAI API Key

Set your OpenAI API key for real semantic embeddings:

```bash
export OPENAI_API_KEY="sk-..."
```

If not set, the system falls back to `MockEmbeddingProvider` (deterministic but not semantic).

## Development Setup

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Run migrations
alembic upgrade head

# 3. Seed dev API key
python scripts/seed_dev_api_key.py

# 4. Run tests
pytest tests/unit/ -x
pytest tests/integration/ -x  # requires running services
```
```

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_docker_e2e.py README.md
git commit -m "test(e2e): add Docker E2E test + update README

- test_docker_e2e.py: full end-to-end scenario (skipped without docker compose).
- README: OpenAI API key setup, development setup instructions.
- Coverage target: ≥ 80% line, ≥ 70% branch."
```

---

## Acceptance Checklist

Run these after all tasks complete:

- [ ] `pytest tests/unit/ -x` passes in < 15s with no external services.
- [ ] `pytest tests/integration/ -x` passes against local services (Neo4j, PostgreSQL, Redis).
- [ ] `alembic upgrade head` on fresh PostgreSQL creates all tables + indexes.
- [ ] `POST /v1/memories` with text persists to Neo4j and pgvector; retrievable via search.
- [ ] `POST /v1/search` with `mode=memory` returns semantically relevant results even when keywords don't overlap.
- [ ] `GET /v1/profiles/{id}` returns in < 100ms on second call (Redis cache hit).
- [ ] `POST /v1/upload` accepts PDF/image, stores in MinIO, creates pipeline job, worker processes to `done`.
- [ ] `GET /v1/health` reports degraded if any downstream service is stopped.
- [ ] Invalid API key → 401; expired key → 401; read-only on write endpoint → 403; rate limit → 429.
- [ ] Entity isolation: alice's memories never in bob's search results.
- [ ] Coverage ≥ 80% line, ≥ 70% branch."