# Emerald M1.5 — Infrastructure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Spec reference:** `docs/superpowers/specs/2026-05-25-infra-hardening-design.md`

**Goal:** Replace all in-memory stubs with real database drivers (Neo4j, pgvector, Redis, MinIO) and wire them into the production API, authentication, Celery pipeline, and health checks.

**Architecture:** Bottom-up: drivers → core stores → embedder/search → Celery pipeline → API layer → tests. Each layer is testable independently before the next layer consumes it.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), neo4j Python driver 5.x, pgvector, redis-py, minio, Celery 5.x, pytest, testcontainers, fakeredis.

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `emerald/async_utils.py` | `run_async()` decorator for sync Celery tasks calling async helpers |
| `migrations/versions/002_add_pgvector_embedding.py` | Drop JSONB `embedding` column, add `vector(1536)`, create HNSW index |
| `migrations/versions/003_add_pipeline_jobs_content_type.py` | Add `content_type` column to `pipeline_jobs` |
| `scripts/seed_dev_api_key.py` | Bootstrap a test API key for local development / E2E tests |
| `tests/unit/test_embedder.py` | Embedding provider unit tests (Mock determinism, OpenAI batching, cache) |
| `tests/unit/test_graph_store.py` | GraphStore CRUD, temporal filter, atomic update (in-memory mode) |
| `tests/unit/test_vector_store.py` | VectorStore store/search, cosine similarity, entity isolation (in-memory mode) |
| `tests/unit/test_extractor_registry.py` | Registry register/get/unsupported/fallback |
| `tests/unit/test_chunker_registry.py` | Registry register/get/unsupported/fallback |
| `tests/unit/test_exceptions.py` | Exception hierarchy, retryable flags |
| `tests/unit/test_config.py` | Settings env loading, defaults |
| `tests/integration/test_neo4j_graph.py` | Neo4j CRUD, constraint validation, UPDATES atomicity (testcontainer) |
| `tests/integration/test_pgvector.py` | pgvector insert/search, HNSW index, cosine accuracy (testcontainer) |
| `tests/integration/test_redis_cache.py` | Profile cache set/get/invalidate, TTL (fakeredis or testcontainer) |
| `tests/integration/test_auth.py` | Key validation, expiry, permissions, rate limiting |
| `tests/integration/test_celery_pipeline.py` | Task chain execution, retry, status transitions (memory broker) |
| `tests/integration/test_docker_e2e.py` | Single test: full add → search → profile → upload → pipeline → isolation |

### Modified Files

| File | Changes |
|---|---|
| `pyproject.toml` | Add `tenacity`, `fakeredis`, `testcontainers` to dev deps |
| `emerald/api/app.py` | Lifespan: init/close Neo4j, Redis, PG engine |
| `emerald/db/neo4j.py` | Module-level driver lifecycle; `init_neo4j()` / `close_neo4j()` / `get_neo4j_driver()` |
| `emerald/db/redis.py` | Module-level client lifecycle; `init_redis()` / `close_redis()` |
| `emerald/core/graph.py` | `use_db=True` branch with real Neo4j Cypher; keep `use_db=False` fallback |
| `emerald/core/vector.py` | `use_db=True` branch with real pgvector SQLAlchemy queries |
| `emerald/core/embedder.py` | Implement `OpenAIProvider`; add Redis cache wrapper; auto-fallback to Mock |
| `emerald/core/search.py` | `_search_memory` uses semantic recall (pgvector) + Neo4j filtering |
| `emerald/core/profile.py` | Replace in-memory `_cache` dict with Redis; keep fakeredis fallback for tests |
| `emerald/core/engine.py` | Wire real stores (no interface changes) |
| `emerald/pipeline/orchestrator.py` | `process_async`: write PipelineJob to PG, submit Celery chain |
| `emerald/pipeline/tasks.py` | Real Celery task implementations with `run_async()` + per-task DB lifecycle |
| `emerald/api/dependencies.py` | Real `api_key_auth` (SHA-256 + PG query), `require_write_permission`, rate limit |
| `emerald/api/routes/upload.py` | Full implementation: size validation, MinIO upload, PG Document insert, Celery submit |
| `emerald/api/routes/system.py` | Real health probes for PG, Neo4j, Redis, MinIO, Celery |
| `README.md` | Alpha → Early Access status, accurate setup instructions |

---

## Phase 0: Dependencies & Tooling

### Task 0.1: Add Python Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements-dev.txt`

- [ ] **Step 1: Add new dev dependencies to `pyproject.toml`**

In `[project.optional-dependencies]dev`, add:
```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.0",
    "httpx>=0.27",
    "ruff>=0.3",
    "mypy>=1.8",
    "fakeredis>=2.0",
    "testcontainers>=4.0",
    "tenacity>=8.0",
]
```

- [ ] **Step 2: Add to `requirements-dev.txt`**

Append:
```
fakeredis>=2.0
testcontainers>=4.0
tenacity>=8.0
```

- [ ] **Step 3: Install locally**

```bash
pip install -e ".[dev,extraction]"
```

Expected: installs without errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml requirements-dev.txt
git commit -m "chore(deps): add tenacity, fakeredis, testcontainers for M1.5"
```

---

## Phase 1: Database Driver Lifecycle

### Task 1.1: Neo4j Driver Lifecycle Management

**Files:**
- Modify: `emerald/db/neo4j.py`
- Modify: `emerald/api/app.py`

- [ ] **Step 1: Refactor `emerald/db/neo4j.py` to module-level lifecycle**

Replace the entire file with:

```python
"""Neo4j async driver lifecycle."""

from __future__ import annotations

from neo4j import AsyncGraphDatabase, AsyncDriver

from emerald.config import get_settings

_driver: AsyncDriver | None = None


async def init_neo4j() -> None:
    """Initialize the Neo4j async driver. Called in FastAPI lifespan."""
    global _driver
    settings = get_settings()
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()


async def close_neo4j() -> None:
    """Close the Neo4j async driver."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def get_neo4j_driver() -> AsyncDriver:
    """Return the initialized Neo4j driver.

    Raises RuntimeError if init_neo4j() has not been called.
    """
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized. Call init_neo4j() first.")
    return _driver
```

- [ ] **Step 2: Wire Neo4j into FastAPI lifespan**

In `emerald/api/app.py`, modify the `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    from emerald.core.logging import configure_logging
    configure_logging(level=settings.emerald_log_level)

    from emerald.db.neo4j import init_neo4j
    from emerald.db.redis import init_redis
    from emerald.db.session import session_factory

    await init_neo4j()
    await init_redis()
    # PG engine is initialized at module import; ensure it is healthy
    async with session_factory.session() as s:
        from sqlalchemy import text
        await s.execute(text("SELECT 1"))

    yield

    await close_neo4j()
    from emerald.db.redis import close_redis
    await close_redis()
    await session_factory.close()
```

- [ ] **Step 3: Verify import**

```bash
python -c "from emerald.db.neo4j import init_neo4j, close_neo4j, get_neo4j_driver; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add emerald/db/neo4j.py emerald/api/app.py
git commit -m "feat(db): add Neo4j driver lifecycle + FastAPI lifespan wiring"
```

---

### Task 1.2: Redis Client Lifecycle Management

**Files:**
- Modify: `emerald/db/redis.py`

- [ ] **Step 1: Refactor to module-level lifecycle**

Replace entire file:

```python
"""Redis async client lifecycle."""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from emerald.config import get_settings

_client: Redis | None = None


async def init_redis() -> None:
    """Initialize the Redis async client."""
    global _client
    settings = get_settings()
    _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _client.ping()


async def close_redis() -> None:
    """Close the Redis async client."""
    global _client
    if _client:
        await _client.close()
        _client = None


def get_redis_client() -> Redis:
    """Return the initialized Redis client.

    Raises RuntimeError if init_redis() has not been called.
    """
    if _client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _client


# Legacy dependency function for FastAPI DI
async def get_redis() -> Redis:
    return get_redis_client()
```

- [ ] **Step 2: Verify import**

```bash
python -c "from emerald.db.redis import init_redis, close_redis, get_redis_client; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add emerald/db/redis.py
git commit -m "feat(db): add Redis client lifecycle management"
```

---

### Task 1.3: Async Utils for Celery

**Files:**
- Create: `emerald/async_utils.py`

- [ ] **Step 1: Create `run_async` decorator**

```python
"""Utilities for running async code inside sync contexts (e.g. Celery tasks)."""

from __future__ import annotations

import asyncio
from functools import wraps


def run_async(coro_func):
    """Decorator that runs an async function inside a fresh event loop.

    Usage in Celery tasks:
        @app.task
        def my_task(...):
            return _run_helper(...)

        @run_async
        async def _run_helper(...):
            ...
    """
    @wraps(coro_func)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper
```

- [ ] **Step 2: Verify**

```bash
python -c "from emerald.async_utils import run_async; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add emerald/async_utils.py
git commit -m "feat(utils): add run_async decorator for Celery task async bridging"
```

---

## Phase 2: GraphStore Neo4j Implementation

### Task 2.1: Write Neo4j GraphStore Tests

**Files:**
- Create: `tests/unit/test_graph_store.py`
- Create: `tests/integration/test_neo4j_graph.py`

- [ ] **Step 1: Write unit tests (in-memory mode)**

```python
"""Unit tests for GraphStore (in-memory fallback mode)."""

import pytest
from datetime import datetime, timezone, timedelta

from emerald.core.graph import GraphStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_create_memory_returns_id(graph):
    mid = await graph.create_memory("test content", entity_id="e1")
    assert isinstance(mid, str) and len(mid) > 0


@pytest.mark.asyncio
async def test_create_memory_defaults(graph):
    mid = await graph.create_memory("test", entity_id="e1")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is True
    assert m["memory_type"] == "fact"
    assert m["confidence"] == 0.8
    assert isinstance(m["valid_from"], datetime)


@pytest.mark.asyncio
async def test_get_memory_not_found(graph):
    assert await graph.get_memory("nonexistent") is None


@pytest.mark.asyncio
async def test_list_latest_excludes_expired(graph):
    mid = await graph.create_memory("expired", entity_id="e1")
    # Manually set valid_until to past
    for m in graph._memories.get("e1", []):
        if m["id"] == mid:
            m["valid_until"] = datetime.now(timezone.utc) - timedelta(days=1)
    latest = await graph.list_latest_memories("e1")
    assert not any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_respects_limit(graph):
    for i in range(10):
        await graph.create_memory(f"mem {i}", entity_id="e1")
    latest = await graph.list_latest_memories("e1", limit=3)
    assert len(latest) == 3


@pytest.mark.asyncio
async def test_update_is_latest_with_replaced_by(graph):
    mid = await graph.create_memory("old", entity_id="e1")
    await graph.update_is_latest(mid, False, replaced_by="new_id")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is False
    assert m["replaced_by"] == "new_id"


@pytest.mark.asyncio
async def test_entity_isolation(graph):
    await graph.create_memory("alice", entity_id="alice")
    await graph.create_memory("bob", entity_id="bob")
    alice_mems = await graph.list_latest_memories("alice")
    assert all("bob" not in m["content"] for m in alice_mems)
```

- [ ] **Step 2: Run unit tests — expect PASS (in-memory already works)**

```bash
pytest tests/unit/test_graph_store.py -v
```

Expected: 7 passed.

- [ ] **Step 3: Write integration test skeleton (Neo4j testcontainer)**

```python
"""Integration tests for GraphStore with real Neo4j."""

import pytest
from testcontainers.neo4j import Neo4jContainer

from emerald.core.graph import GraphStore
from emerald.db.neo4j import init_neo4j, close_neo4j, get_neo4j_driver


@pytest.fixture(scope="module")
async def neo4j_graph():
    with Neo4jContainer("neo4j:5-community") as neo4j:
        import os
        os.environ["NEO4J_URI"] = neo4j.get_connection_url()
        os.environ["NEO4J_USER"] = "neo4j"
        os.environ["NEO4J_PASSWORD"] = neo4j.password
        await init_neo4j()
        graph = GraphStore(use_db=True)
        yield graph
        await close_neo4j()


@pytest.mark.asyncio
async def test_neo4j_create_and_get(neo4j_graph):
    mid = await neo4j_graph.create_memory("neo4j test", entity_id="test_e")
    m = await neo4j_graph.get_memory(mid)
    assert m is not None
    assert m["content"] == "neo4j test"
```

- [ ] **Step 4: Run integration test — expect FAIL (GraphStore.use_db=True not implemented)**

```bash
pytest tests/integration/test_neo4j_graph.py -v -x
```

Expected: FAIL with Neo4j methods returning empty/pass results.

- [ ] **Step 5: Commit tests**

```bash
git add tests/unit/test_graph_store.py tests/integration/test_neo4j_graph.py
git commit -m "test(graph): add GraphStore unit + Neo4j integration test skeletons"
```

---

### Task 2.2: Implement GraphStore Neo4j Branch

**Files:**
- Modify: `emerald/core/graph.py`

- [ ] **Step 1: Modify `GraphStore.__init__` to use `get_neo4j_driver()`**

Change `__init__` to:
```python
def __init__(self, use_db: bool = True) -> None:
    self._use_db = use_db
    self._memories: dict[str, list[dict]] = {}
    if use_db:
        self._driver = get_neo4j_driver()
```

- [ ] **Step 2: Implement `create_memory` Neo4j branch**

Add at the top of `create_memory`, before the existing logic:

```python
async def create_memory(self, ...):
    memory_id = uuid4().hex
    now = datetime.now(timezone.utc)

    if self._use_db:
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (e:Entity {id: $entity_id})
                ON CREATE SET e.created_at = datetime(), e.type = "user"
                CREATE (m:Memory {
                    id: $id, content: $content, summary: $summary,
                    memory_type: $memory_type, confidence: $confidence,
                    is_latest: true, valid_from: datetime(),
                    valid_until: $valid_until,
                    replaced_by: null,
                    source_document_id: $document_id,
                    source_type: $source_type,
                    tokens_estimate: $tokens,
                    access_count: 0,
                    last_accessed_at: null,
                    created_at: datetime(),
                    updated_at: datetime()
                })
                CREATE (e)-[:HAS_MEMORY {created_at: datetime()}]->(m)
                """,
                id=memory_id,
                content=content,
                entity_id=entity_id,
                summary=summary or content[:200],
                memory_type=memory_type,
                confidence=confidence,
                valid_until=valid_until.isoformat() if valid_until else None,
                document_id=document_id,
                source_type=source_type,
                tokens=len(content) // 4,
            )
        return memory_id
    # ... existing in-memory logic below ...
```

- [ ] **Step 3: Implement `get_memory` Neo4j branch**

```python
if self._use_db:
    async with self._driver.session() as session:
        result = await session.run(
            "MATCH (m:Memory {id: $id}) RETURN m", id=memory_id
        )
        record = await result.single()
        if record:
            node = record["m"]
            return dict(node)
        return None
```

- [ ] **Step 4: Implement `list_latest_memories` Neo4j branch**

```python
if self._use_db:
    async with self._driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {id: $entity_id})-[:HAS_MEMORY]->(m:Memory)
            WHERE m.is_latest = true
              AND (m.valid_until IS NULL OR m.valid_until > datetime())
            RETURN m
            ORDER BY m.created_at DESC
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        memories = []
        async for record in result:
            memories.append(dict(record["m"]))
        if memory_type:
            memories = [m for m in memories if m.get("memory_type") == memory_type]
        return memories
```

- [ ] **Step 5: Implement `update_is_latest` Neo4j branch**

```python
if self._use_db:
    async with self._driver.session() as session:
        await session.run(
            """
            MATCH (m:Memory {id: $id})
            SET m.is_latest = $is_latest,
                m.replaced_by = $replaced_by,
                m.updated_at = datetime()
            """,
            id=memory_id,
            is_latest=is_latest,
            replaced_by=replaced_by,
        )
    return
```

- [ ] **Step 6: Run unit tests — still PASS**

```bash
pytest tests/unit/test_graph_store.py -v
```

Expected: 7 passed.

- [ ] **Step 7: Run integration tests — should now PASS**

```bash
pytest tests/integration/test_neo4j_graph.py -v -x
```

Expected: test passes.

- [ ] **Step 8: Commit**

```bash
git add emerald/core/graph.py
git commit -m "feat(graph): implement GraphStore Neo4j driver branch"
```

---

## Phase 3: VectorStore pgvector Implementation

### Task 3.1: Write VectorStore Tests

**Files:**
- Create: `tests/unit/test_vector_store.py`
- Create: `tests/integration/test_pgvector.py`
- Create: `migrations/versions/002_add_pgvector_embedding.py`

- [ ] **Step 1: Write unit tests (in-memory mode)**

```python
"""Unit tests for VectorStore (in-memory fallback mode)."""

import pytest
import math

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
async def test_search_empty_store(vector):
    results = await vector.search([1.0, 0.0], entity_id="e1", top_k=5)
    assert results == []
```

- [ ] **Step 2: Run unit tests — PASS**

```bash
pytest tests/unit/test_vector_store.py -v
```

Expected: 6 passed.

- [ ] **Step 3: Create Alembic migration for pgvector**

```python
"""Add pgvector embedding column

Revision ID: 002
Revises: 35500f582718
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "002_add_pgvector_embedding"
down_revision = "35500f582718"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_column("embeddings", "embedding")
    op.add_column(
        "embeddings",
        sa.Column("embedding", sa.dialects.postgresql.JSONB, nullable=True),  # placeholder
    )
    # Note: actual vector type will be set via raw SQL after pgvector extension is available
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX idx_embeddings_hnsw ON embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw")
    op.drop_column("embeddings", "embedding")
    op.add_column(
        "embeddings",
        sa.Column("embedding", sa.dialects.postgresql.JSONB, nullable=False),
    )
```

Wait, this won't work cleanly. Let me think... The `vector` type from pgvector might not be available in Alembic's `sa.dialects.postgresql`. Better approach: use raw SQL entirely for the column type.

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.execute(
        "CREATE INDEX idx_embeddings_hnsw ON embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw")
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding JSONB NOT NULL DEFAULT '{}'")
```

- [ ] **Step 4: Write pgvector integration test skeleton**

```python
"""Integration tests for VectorStore with real PostgreSQL/pgvector."""

import pytest
from testcontainers.postgres import PostgresContainer

from emerald.core.vector import VectorStore
from emerald.db.session import SessionFactory


@pytest.fixture(scope="module")
async def pg_vector():
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        import os
        db_url = postgres.get_connection_url().replace("postgresql://", "postgresql+asyncpg://")
        os.environ["DATABASE_URL"] = db_url
        factory = SessionFactory(db_url)
        # Run migrations
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url.replace("+asyncpg", ""))
        command.upgrade(alembic_cfg, "head")
        vector = VectorStore(use_db=True)
        yield vector
        await factory.close()


@pytest.mark.asyncio
async def test_pgvector_store_and_search(pg_vector):
    emb = [1.0] + [0.0] * 1535
    await pg_vector.store("c1", "hello", emb, entity_id="e1")
    results = await pg_vector.search(emb, entity_id="e1", top_k=5)
    assert len(results) == 1
    assert results[0][1] == "hello"
    assert results[0][2] > 0.99
```

- [ ] **Step 5: Run integration test — expect FAIL**

```bash
pytest tests/integration/test_pgvector.py -v -x
```

Expected: FAIL (VectorStore.use_db=True branch not implemented).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_vector_store.py tests/integration/test_pgvector.py migrations/versions/002_add_pgvector_embedding.py
git commit -m "test(vector): add VectorStore tests + pgvector migration skeleton"
```

---

### Task 3.2: Implement VectorStore pgvector Branch

**Files:**
- Modify: `emerald/core/vector.py`

- [ ] **Step 1: Add SQLAlchemy imports and change `__init__`**

```python
from emerald.db.session import session_factory
from sqlalchemy import text, insert, select
```

Change `__init__`:
```python
def __init__(self, use_db: bool = True) -> None:
    self._use_db = use_db
    self._memory_store: dict[str, list[float]] = {}
    self._memory_texts: dict[str, str] = {}
    self._memory_entities: dict[str, str] = {}
```

- [ ] **Step 2: Implement `store` pgvector branch**

Add at the top of `store`:
```python
async def store(self, chunk_id, text, embedding, *, entity_id, ...):
    if self._use_db:
        async with session_factory.session() as session:
            await session.execute(
                text("""
                INSERT INTO embeddings (chunk_id, text, embedding, entity_id, document_id, model_name, dimensions)
                VALUES (:chunk_id, :text, :embedding, :entity_id, :document_id, :model_name, :dimensions)
                """),
                {
                    "chunk_id": chunk_id,
                    "text": text,
                    "embedding": str(embedding),  # pgvector accepts list literal or string
                    "entity_id": entity_id,
                    "document_id": document_id,
                    "model_name": model_name,
                    "dimensions": len(embedding),
                },
            )
        return
    # ... existing in-memory logic ...
```

Wait — pgvector with SQLAlchemy async needs special handling. The `vector` type might need `pgvector.sqlalchemy.Vector` type or we can pass it as a Python list if the driver supports it. Let me check... Actually with `asyncpg`, passing a Python list for a `vector` column should work if pgvector is installed. But we need to be careful.

Alternative: use raw SQL with `ARRAY` cast or just pass the list.

```python
"embedding": embedding,  # Python list — asyncpg + pgvector should accept this
```

- [ ] **Step 3: Implement `search` pgvector branch**

```python
if self._use_db:
    async with session_factory.session() as session:
        result = await session.execute(
            text("""
            SELECT chunk_id, text, 1 - (embedding <=> :query_embedding) AS score
            FROM embeddings
            WHERE entity_id = :entity_id
            ORDER BY embedding <=> :query_embedding
            LIMIT :top_k
            """),
            {
                "query_embedding": query_embedding,
                "entity_id": entity_id,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [(row.chunk_id, row.text, float(row.score)) for row in rows]
```

- [ ] **Step 4: Run unit tests — PASS**

```bash
pytest tests/unit/test_vector_store.py -v
```

- [ ] **Step 5: Run integration tests**

```bash
pytest tests/integration/test_pgvector.py -v -x
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add emerald/core/vector.py
git commit -m "feat(vector): implement VectorStore pgvector driver branch"
```

---

## Phase 4: Redis-Backed ProfileManager

### Task 4.1: Implement Redis Profile Cache

**Files:**
- Modify: `emerald/core/profile.py`
- Create: `tests/integration/test_redis_cache.py`

- [ ] **Step 1: Modify `ProfileManager.__init__`**

Replace the `__init__` to accept an optional redis client:

```python
class ProfileManager:
    def __init__(
        self,
        graph: GraphStore | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self._redis = redis_client
        self._ttl = 24 * 3600

    def _get_redis(self) -> Redis | None:
        if self._redis is not None:
            return self._redis
        try:
            from emerald.db.redis import get_redis_client
            return get_redis_client()
        except RuntimeError:
            return None
```

Remove the `self._cache: dict` and `self._versions` (or keep `_versions` for versioning logic but not as cache).

- [ ] **Step 2: Modify `ProfileManager.get`**

```python
async def get(self, entity_id: str) -> EntityProfile:
    redis = self._get_redis()
    if redis:
        cached = await redis.get(f"profile:{entity_id}")
        if cached:
            import json
            data = json.loads(cached)
            return EntityProfile(
                entity_id=data["entity_id"],
                static=[ProfileFact(**f) for f in data["static"]],
                dynamic=[ProfileFact(**f) for f in data["dynamic"]],
                memory_count=data["memory_count"],
                computed_at=data["computed_at"],
                version=data["version"],
            )

    profile = await self.compute(entity_id)

    if redis:
        import json
        await redis.setex(
            f"profile:{entity_id}",
            self._ttl,
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
```

- [ ] **Step 3: Modify `ProfileManager.invalidate`**

```python
async def invalidate(self, entity_id: str) -> None:
    redis = self._get_redis()
    if redis:
        await redis.delete(f"profile:{entity_id}")
        logger.info("profile.cache.invalidated", entity_id=entity_id)
```

- [ ] **Step 4: Write Redis cache integration test**

```python
"""Integration tests for ProfileManager Redis caching."""

import pytest
import fakeredis.aioredis

from emerald.core.profile import ProfileManager
from emerald.core.graph import GraphStore


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def profile_mgr(fake_redis):
    return ProfileManager(graph=GraphStore(use_db=False), redis_client=fake_redis)


@pytest.mark.asyncio
async def test_profile_cache_miss_then_hit(profile_mgr, fake_redis):
    # Seed a memory
    await profile_mgr.graph.create_memory("test fact", entity_id="e1", memory_type="fact", confidence=0.9)

    # First call — cache miss, computes from graph
    p1 = await profile_mgr.get("e1")
    assert p1.memory_count == 1

    # Second call — cache hit
    p2 = await profile_mgr.get("e1")
    assert p2.memory_count == 1

    # Verify Redis has the key
    assert await fake_redis.exists("profile:e1")


@pytest.mark.asyncio
async def test_profile_invalidate(profile_mgr, fake_redis):
    await profile_mgr.graph.create_memory("fact", entity_id="e1", confidence=0.9)
    await profile_mgr.get("e1")
    assert await fake_redis.exists("profile:e1")

    await profile_mgr.invalidate("e1")
    assert not await fake_redis.exists("profile:e1")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/core/test_profile_manager.py tests/integration/test_redis_cache.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add emerald/core/profile.py tests/integration/test_redis_cache.py
git commit -m "feat(profile): implement Redis-backed profile cache with fakeredis tests"
```

---

## Phase 5: OpenAI Embedder + Cache

### Task 5.1: Implement OpenAIProvider

**Files:**
- Modify: `emerald/core/embedder.py`
- Create: `tests/unit/test_embedder.py`

- [ ] **Step 1: Add tenacity retry to OpenAIProvider**

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class OpenAIProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # OpenAI supports up to 2048 texts per request
        BATCH_SIZE = 2048
        all_embeddings = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            response = await self._client.post(
                "/embeddings",
                json={"model": self._model, "input": batch},
            )
            response.raise_for_status()
            data = response.json()["data"]
            # Sort by index to preserve order
            data.sort(key=lambda d: d["index"])
            all_embeddings.extend([d["embedding"] for d in data])
        return all_embeddings

    def dimension(self) -> int:
        return self._dimensions_map.get(self._model, 1536)
```

- [ ] **Step 2: Update `get_embedding_provider` with auto-fallback**

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

    if settings.embedding_provider in (EmbeddingProviderEnum.bge, EmbeddingProviderEnum.local):
        return LocalProvider(model_path=settings.bge_model_path, dimension=1024)

    # Default fallback
    return MockEmbeddingProvider(dimension=1536)
```

- [ ] **Step 3: Write embedder unit tests**

```python
"""Unit tests for embedding providers."""

import pytest
from emerald.core.embedder import MockEmbeddingProvider, OpenAIProvider, get_embedding_provider


def test_mock_embedder_deterministic():
    p = MockEmbeddingProvider(dimension=128)
    import asyncio
    emb1 = asyncio.run(p.embed(["hello"]))[0]
    emb2 = asyncio.run(p.embed(["hello"]))[0]
    assert emb1 == emb2


def test_mock_embedder_different_inputs():
    p = MockEmbeddingProvider(dimension=128)
    import asyncio
    emb1 = asyncio.run(p.embed(["hello"]))[0]
    emb2 = asyncio.run(p.embed(["world"]))[0]
    assert emb1 != emb2


def test_mock_embedder_dimension():
    p = MockEmbeddingProvider(dimension=256)
    import asyncio
    emb = asyncio.run(p.embed(["test"]))[0]
    assert len(emb) == 256


def test_mock_embedder_empty_list():
    p = MockEmbeddingProvider(dimension=128)
    import asyncio
    assert asyncio.run(p.embed([])) == []


def test_openai_provider_raises_without_key():
    # When openai_api_key is empty, factory falls back to Mock
    import os
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["EMBEDDING_PROVIDER"] = "openai"
    p = get_embedding_provider()
    assert isinstance(p, MockEmbeddingProvider)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_embedder.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add emerald/core/embedder.py tests/unit/test_embedder.py
git commit -m "feat(embedder): implement OpenAIProvider with retry + batching + auto-fallback"
```

---

### Task 5.2: Add Embedding Cache in MemoryEngine

**Files:**
- Modify: `emerald/core/engine.py`

- [ ] **Step 1: Modify `_embed` to add Redis cache**

```python
async def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
    texts = [c.text for c in chunks]
    if not texts:
        return []

    # Check Redis cache
    try:
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
    except RuntimeError:
        redis = None

    import hashlib, json

    embeddings: list[list[float] | None] = [None] * len(texts)
    texts_to_embed: list[str] = []
    indices: list[int] = []

    for i, text in enumerate(texts):
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        if redis:
            cached = await redis.get(f"embedding:{text_hash}")
            if cached:
                embeddings[i] = json.loads(cached)
                continue
        texts_to_embed.append(text)
        indices.append(i)

    if texts_to_embed:
        new_embeddings = await self.embedder.embed(texts_to_embed)
        for idx, emb in zip(indices, new_embeddings):
            embeddings[idx] = emb
            if redis:
                text_hash = hashlib.sha256(texts[idx].encode()).hexdigest()
                await redis.setex(f"embedding:{text_hash}", 7 * 24 * 3600, json.dumps(emb))

    return [e for e in embeddings if e is not None]
```

- [ ] **Step 2: Run existing engine tests**

```bash
pytest tests/core/test_memory_engine.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add emerald/core/engine.py
git commit -m "feat(engine): add Redis embedding cache to avoid repeated API calls"
```

---

## Phase 6: Semantic Hybrid Search

### Task 6.1: Overhaul Memory Search

**Files:**
- Modify: `emerald/core/search.py`
- Modify: `tests/core/test_search.py`

- [ ] **Step 1: Rewrite `_search_memory`**

```python
async def _search_memory(
    self, q: str, entity_id: str, top_k: int, filters: dict | None,
) -> list[SearchResult]:
    if not self.embedder:
        return []

    query_embedding = (await self.embedder.embed([q]))[0]
    semantic_hits = await self.vector.search(
        query_embedding, entity_id=entity_id, top_k=top_k * 2,
    )

    results = []
    now = datetime.now(timezone.utc)

    for chunk_id, text, vec_score in semantic_hits:
        memory = await self.graph.get_memory(chunk_id)
        if not memory:
            continue
        if not memory.get("is_latest", True):
            continue
        valid_until = memory.get("valid_until")
        if valid_until is not None and valid_until < now:
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
```

- [ ] **Step 2: Update search tests**

The existing `tests/core/test_search.py` uses MockEmbeddingProvider and in-memory stores. These tests should still pass because the semantic hits from MockEmbeddingProvider are deterministic (same text → high similarity). However, we need to ensure that memory embeddings are stored in VectorStore during test setup.

In the `populated` fixture, add vector store population:

```python
# In the populated fixture, after creating each memory, also store its embedding:
emb = (await embedder.embed([content]))[0]
await vector.store(mid, content, emb, entity_id=entity_id)
```

This may already be there — check the existing test file.

- [ ] **Step 3: Run search tests**

```bash
pytest tests/core/test_search.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add emerald/core/search.py tests/core/test_search.py
git commit -m "feat(search): replace keyword memory search with semantic pgvector + Neo4j filtering"
```

---

## Phase 7: Celery Pipeline

### Task 7.1: Implement Celery Tasks

**Files:**
- Modify: `emerald/pipeline/tasks.py`
- Modify: `emerald/pipeline/orchestrator.py`

- [ ] **Step 1: Implement real Celery tasks**

Replace `emerald/pipeline/tasks.py`:

```python
"""Pipeline Celery tasks — async task chain for processing."""

from __future__ import annotations

import structlog
from celery import shared_task

from emerald.async_utils import run_async
from emerald.config import get_settings

logger = structlog.get_logger(__name__)


# ---- Helper: update pipeline status in PG ----

@run_async
async def _update_status(pipeline_id: str, status: str) -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text
    async with session_factory.session() as session:
        await session.execute(
            text("UPDATE pipeline_jobs SET status = :status, updated_at = NOW() WHERE id = :id"),
            {"status": status, "id": pipeline_id},
        )


@run_async
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


# ---- Task implementations ----

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    return _run_extract(self, pipeline_id, content, content_type)


@run_async
async def _run_extract(task_self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "extracting")
        from emerald.pipeline.extraction.registry import ExtractorRegistry
        registry = ExtractorRegistry()
        extractor = registry.get(content_type)
        result = await extractor.extract(content)

        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        await redis.set(f"pipeline:{pipeline_id}:extracted", result.text)

        return {"pipeline_id": pipeline_id, "content_type": content_type}
    except Exception as exc:
        await _update_error(pipeline_id, "extracting", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def chunk_task(self, prev_result: dict) -> dict:
    return _run_chunk(self, prev_result)


@run_async
async def _run_chunk(task_self, prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    content_type = prev_result["content_type"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "chunking")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        extracted_text = await redis.get(f"pipeline:{pipeline_id}:extracted")

        from emerald.pipeline.chunking.registry import ChunkerRegistry
        chunker = ChunkerRegistry().get(content_type)
        chunks = chunker.chunk(extracted_text or "")

        import json
        await redis.set(
            f"pipeline:{pipeline_id}:chunks",
            json.dumps([{"id": c.id, "text": c.text, "index": c.index, "token_count": c.token_count, "content_type": c.content_type, "metadata": c.metadata} for c in chunks]),
        )
        return {"pipeline_id": pipeline_id, "chunk_count": len(chunks)}
    except Exception as exc:
        await _update_error(pipeline_id, "chunking", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def embed_task(self, prev_result: dict) -> dict:
    return _run_embed(self, prev_result)


@run_async
async def _run_embed(task_self, prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "embedding")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        import json
        chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
        chunks_data = json.loads(chunks_raw or "[]")
        texts = [c["text"] for c in chunks_data]

        from emerald.core.embedder import get_embedding_provider
        provider = get_embedding_provider()
        embeddings = await provider.embed(texts)

        await redis.set(
            f"pipeline:{pipeline_id}:embeddings",
            json.dumps(embeddings),
        )
        return {"pipeline_id": pipeline_id}
    except Exception as exc:
        await _update_error(pipeline_id, "embedding", str(exc))
        raise task_self.retry(exc=exc)
    finally:
        await close_neo4j()


@shared_task(bind=True)
def index_task(self, prev_result: dict, entity_id: str) -> dict:
    return _run_index(self, prev_result, entity_id)


@run_async
async def _run_index(task_self, prev_result: dict, entity_id: str) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import init_neo4j, close_neo4j
    await init_neo4j()
    try:
        await _update_status(pipeline_id, "indexing")
        from emerald.db.redis import get_redis_client
        redis = get_redis_client()
        import json
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
                chunk_id=chunk_data["id"],
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
    return _run_postprocess(prev_result, entity_id)


@run_async
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
        for key in ["extracted", "chunks", "embeddings"]:
            await redis.delete(f"pipeline:{pipeline_id}:{key}")

        await _update_status(pipeline_id, "done")
    finally:
        await close_neo4j()
```

- [ ] **Step 2: Update orchestrator `process_async`**

In `emerald/pipeline/orchestrator.py`, replace the `process_async` stub:

```python
async def process_async(
    self,
    content: str | bytes,
    *,
    content_type: str,
    entity_id: str,
    document_id: str | None = None,
) -> str:
    from hashlib import sha256
    from sqlalchemy import insert
    from emerald.models.pipeline_job import PipelineJob
    from emerald.db.session import session_factory

    pipeline_id = uuid4().hex
    content_hash = sha256(
        content.encode() if isinstance(content, str) else content
    ).hexdigest()

    async with session_factory.session() as session:
        await session.execute(
            insert(PipelineJob).values(
                id=pipeline_id,
                entity_id=entity_id,
                document_id=document_id,
                content_hash=content_hash,
                status="queued",
                content_type=content_type,
            )
        )

    from emerald.pipeline.tasks import (
        extract_task, chunk_task, embed_task, index_task, postprocess_task,
    )
    from celery import chain

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
```

- [ ] **Step 3: Write Celery pipeline integration test**

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
    result = extract_task.run("pipe_1", "hello world", "text")
    assert result["pipeline_id"] == "pipe_1"
    assert result["content_type"] == "text"


def test_chunk_task_follows_extract(celery_app):
    prev = {"pipeline_id": "pipe_1", "content_type": "text"}
    result = chunk_task.run(prev)
    assert result["pipeline_id"] == "pipe_1"
    assert result["chunk_count"] >= 1
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/integration/test_celery_pipeline.py -v
```

Expected: passes (task_always_eager runs tasks synchronously).

- [ ] **Step 5: Commit**

```bash
git add emerald/pipeline/tasks.py emerald/pipeline/orchestrator.py tests/integration/test_celery_pipeline.py
git commit -m "feat(pipeline): implement real Celery task chain with PG status tracking"
```

---

## Phase 8: Upload, Auth, Health

### Task 8.1: Implement Upload Endpoint

**Files:**
- Modify: `emerald/api/routes/upload.py`
- Create: `migrations/versions/003_add_pipeline_jobs_content_type.py`

- [ ] **Step 1: Create migration for `pipeline_jobs.content_type`**

```python
"""Add content_type to pipeline_jobs

Revision ID: 003
Revises: 002_add_pgvector_embedding
"""

from alembic import op
import sqlalchemy as sa

revision = "003_add_pipeline_jobs_content_type"
down_revision = "002_add_pgvector_embedding"


def upgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("content_type", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "content_type")
```

- [ ] **Step 2: Implement upload route**

Replace `emerald/api/routes/upload.py`:

```python
"""Upload routes — POST /v1/upload + GET /v1/pipelines/{id} + GET /v1/files."""

from __future__ import annotations

import uuid
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import insert, select

from emerald.api.dependencies import api_key_auth, require_write_permission
from emerald.config import get_settings
from emerald.core.exceptions import ContentTooLargeError
from emerald.db.minio import minio_client
from emerald.db.session import session_factory
from emerald.models.document import Document
from emerald.models.pipeline_job import PipelineJob
from emerald.pipeline.orchestrator import PipelineOrchestrator

router = APIRouter(tags=["Upload"])

MAX_FILE_SIZE = 50 * 1024 * 1024


def _detect_mime(filename: str | None) -> str:
    if not filename:
        return "application/octet-stream"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain",
        "md": "text/markdown",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "mp4": "video/mp4",
        "py": "text/x-python",
        "js": "text/javascript",
        "ts": "text/typescript",
    }
    return mapping.get(ext, "application/octet-stream")


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
) -> dict:
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise ContentTooLargeError(limit_mb=50, actual=len(contents))

    detected = content_type or _detect_mime(file.filename)
    storage_key = f"{entity_id}/{uuid.uuid4().hex}/{file.filename or 'untitled'}"

    minio_client.client.put_object(
        settings.minio_bucket,
        storage_key,
        io.BytesIO(contents),
        len(contents),
        content_type=detected,
    )

    doc_id = uuid.uuid4()
    async with session_factory.session() as session:
        await session.execute(
            insert(Document).values(
                id=doc_id,
                entity_id=entity_id,
                title=title or file.filename or "untitled",
                content_type=detected,
                storage_key=storage_key,
                file_size_bytes=len(contents),
                status="queued",
            )
        )

    orchestrator = PipelineOrchestrator()
    pipeline_id = await orchestrator.process_async(
        content=contents,
        content_type=detected,
        entity_id=entity_id,
        document_id=str(doc_id),
    )

    return {
        "data": {
            "document_id": str(doc_id),
            "pipeline_id": pipeline_id,
            "pipeline_status": "queued",
            "file_size_bytes": len(contents),
            "content_type": detected,
            "title": title or file.filename,
        }
    }


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_status(pipeline_id: str) -> dict:
    async with session_factory.session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PipelineJob).where(PipelineJob.id == pipeline_id)
        )
        row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    return {
        "data": {
            "pipeline_id": str(row.id),
            "status": row.status,
            "stage": row.status,
            "document_id": str(row.document_id) if row.document_id else None,
            "content_type": row.content_type,
            "chunk_count": row.chunk_count,
            "error_message": row.error_message,
        }
    }
```

- [ ] **Step 3: Add `ContentTooLargeError` to exceptions if missing**

In `emerald/core/exceptions.py`, add:

```python
class ContentTooLargeError(EmeraldError):
    def __init__(self, limit_mb: int, actual: int) -> None:
        super().__init__(
            f"Content too large: {actual / 1024 / 1024:.1f}MB (limit: {limit_mb}MB)"
        )
        self.limit_mb = limit_mb
        self.actual_bytes = actual
```

- [ ] **Step 4: Run upload API tests**

```bash
pytest tests/api/test_api.py -v -k upload
```

Expected: may need to adjust existing tests; ensure they pass.

- [ ] **Step 5: Commit**

```bash
git add emerald/api/routes/upload.py emerald/core/exceptions.py migrations/versions/003_add_pipeline_jobs_content_type.py
git commit -m "feat(upload): implement full upload endpoint with MinIO + PG + Celery"
```

---

### Task 8.2: Implement API Key Authentication

**Files:**
- Modify: `emerald/api/dependencies.py`
- Create: `tests/integration/test_auth.py`

- [ ] **Step 1: Implement real auth dependencies**

Replace `emerald/api/dependencies.py`:

```python
"""API authentication dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey


async def api_key_auth(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer em_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Use: Bearer em_<key>",
        )

    api_key = auth_header.removeprefix("Bearer ")
    key_hash = sha256(api_key.encode()).hexdigest()

    async with session_factory.session() as session:
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True,
            )
        )
        key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if key_record.expires_at and key_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired",
        )

    request.state.entity_id = str(key_record.entity_id)
    request.state.permissions = key_record.permissions or []
    request.state.api_key_id = str(key_record.id)
    return "authenticated"


async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write permission required",
        )
    return "authorized"


# Rate limits per endpoint per minute
RATE_LIMITS = {
    "/v1/memories": 60,
    "/v1/search": 120,
    "/v1/profiles/": 300,
    "/v1/upload": 10,
}


async def rate_limit_dependency(request: Request) -> None:
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return
    endpoint = request.url.path
    limit = 60
    for prefix, l in RATE_LIMITS.items():
        if endpoint.startswith(prefix) or endpoint == prefix:
            limit = l
            break
    window = 60

    from emerald.db.redis import get_redis_client
    try:
        redis = get_redis_client()
    except RuntimeError:
        return  # Redis unavailable — skip rate limiting

    key = f"rate_limit:{key_id}:{endpoint}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    if current > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(window)},
        )
```

- [ ] **Step 2: Wire auth into routes**

In each route file (`memories.py`, `search.py`, `profiles.py`, `upload.py`), update the router to include auth dependencies. Example for `memories.py`:

```python
from emerald.api.dependencies import api_key_auth, rate_limit_dependency

@router.post("/memories", dependencies=[Depends(rate_limit_dependency)])
async def add_memory(...):
    ...
```

And add `Depends(api_key_auth)` to the route functions that don't already have it (upload already does).

Actually, the cleanest approach is to add auth at the router level in `app.py` or use `dependencies` parameter. For minimal change, add `Depends(api_key_auth)` to each route that needs it.

- [ ] **Step 3: Write auth integration tests**

```python
"""Integration tests for API Key authentication."""

import pytest
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from fastapi.testclient import TestClient
from emerald.api.app import create_app
from emerald.core.engine import MemoryEngine
from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey
from emerald.models.entity import Entity


@pytest.fixture
def client_with_auth():
    app = create_app(engine=MemoryEngine(use_db=False))
    return TestClient(app)


def test_missing_api_key(client_with_auth):
    resp = client_with_auth.post("/v1/memories", json={"content": "test", "entity_id": "e1"})
    assert resp.status_code == 401


def test_invalid_api_key(client_with_auth):
    resp = client_with_auth.post(
        "/v1/memories",
        json={"content": "test", "entity_id": "e1"},
        headers={"Authorization": "Bearer em_invalid"},
    )
    assert resp.status_code == 401
```

Note: These tests require a real database to create API keys. For now, keep them simple or mark them to skip until the seed script is ready.

- [ ] **Step 4: Run existing API tests — some may now 401**

```bash
pytest tests/api/test_api.py -v
```

Expected: some tests fail with 401 because auth is now enforced. We need to update the test fixture to inject a mock auth or seed a test key.

- [ ] **Step 5: Update API test fixture to bypass auth for unit tests**

In `tests/api/test_api.py`, update the `client` fixture to create an app with a mock auth override:

```python
@pytest.fixture
def client(engine):
    app = create_app(engine=engine)
    # Override auth dependency for unit tests
    from emerald.api.dependencies import api_key_auth, require_write_permission
    app.dependency_overrides[api_key_auth] = lambda: "test_auth"
    app.dependency_overrides[require_write_permission] = lambda: "test_auth"
    return TestClient(app)
```

- [ ] **Step 6: Re-run API tests**

```bash
pytest tests/api/test_api.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add emerald/api/dependencies.py tests/api/test_api.py tests/integration/test_auth.py
git commit -m "feat(auth): implement SHA-256 API Key auth + rate limiting + permission checks"
```

---

### Task 8.3: Real Health Check

**Files:**
- Modify: `emerald/api/routes/system.py`

- [ ] **Step 1: Replace health check with real probes**

```python
"""System routes — health check and metrics."""

from __future__ import annotations

from fastapi import APIRouter

from emerald.config import get_settings

router = APIRouter(tags=["System"])


@router.get("/health", response_model=dict)
async def health_check() -> dict:
    checks = {}
    overall = "ok"

    # PostgreSQL
    try:
        from emerald.db.session import session_factory
        from sqlalchemy import text
        async with session_factory.session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall = "degraded"

    # Neo4j
    try:
        from emerald.db.neo4j import get_neo4j_driver
        driver = get_neo4j_driver()
        await driver.verify_connectivity()
        checks["neo4j"] = "ok"
    except Exception as e:
        checks["neo4j"] = f"error: {e}"
        overall = "degraded"

    # Redis
    try:
        from emerald.db.redis import get_redis_client
        await get_redis_client().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall = "degraded"

    # MinIO
    try:
        from emerald.db.minio import minio_client
        minio_client.client.list_buckets()
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"error: {e}"
        overall = "degraded"

    # Celery
    try:
        from emerald.pipeline.celery import celery_app
        insp = celery_app.control.inspect(timeout=0.5)
        active = insp.active()
        checks["celery"] = "ok" if active is not None else "no_workers"
        if active is None:
            overall = "degraded"
    except Exception as e:
        checks["celery"] = f"error: {e}"
        overall = "degraded"

    return {
        "status": overall,
        "version": "0.1.0",
        "checks": checks,
    }
```

- [ ] **Step 2: Run health check test**

```bash
pytest tests/api/test_api.py::test_health_check -v
```

Expected: passes (with `use_db=False`, Neo4j/Redis may report error but that's fine for unit tests).

- [ ] **Step 3: Commit**

```bash
git add emerald/api/routes/system.py
git commit -m "feat(health): implement real service probes with degraded state reporting"
```

---

## Phase 9: Unit Test Hardening

### Task 9.1: Fill Unit Test Gaps

**Files:**
- Create: `tests/unit/test_extractor_registry.py`
- Create: `tests/unit/test_chunker_registry.py`
- Create: `tests/unit/test_exceptions.py`
- Create: `tests/unit/test_config.py`
- Modify: `tests/negative/test_no_internal_exposure.py` (if needed)

- [ ] **Step 1: Write registry tests**

```python
# tests/unit/test_extractor_registry.py
import pytest
from emerald.pipeline.extraction.registry import ExtractorRegistry, UnsupportedContentType
from emerald.pipeline.extraction.text import TextExtractor


def test_register_and_get():
    reg = ExtractorRegistry()
    reg.register("text", TextExtractor())
    extractor = reg.get("text")
    assert extractor.supports("text")


def test_register_overwrite():
    reg = ExtractorRegistry()
    reg.register("text", TextExtractor())
    reg.register("text", TextExtractor())
    assert reg.get("text") is not None


def test_get_unsupported_raises():
    reg = ExtractorRegistry()
    with pytest.raises(UnsupportedContentType):
        reg.get("unknown")
```

(Same pattern for chunker registry.)

- [ ] **Step 2: Write exception tests**

```python
# tests/unit/test_exceptions.py
import pytest
from emerald.core.exceptions import (
    EmeraldError, ExtractionError, EmbeddingError, NotFoundError, ContentTooLargeError,
)


def test_emerald_error_base():
    with pytest.raises(EmeraldError):
        raise ExtractionError("pdf", "fail")


def test_extraction_error_retryable():
    e = ExtractionError("pdf", "fail", retryable=True)
    assert e.retryable is True
    e2 = ExtractionError("pdf", "fail", retryable=False)
    assert e2.retryable is False


def test_not_found_error_message():
    e = NotFoundError("memory", "mem_123")
    assert "memory" in str(e)
    assert "mem_123" in str(e)


def test_content_too_large_error():
    e = ContentTooLargeError(limit_mb=50, actual=100_000_000)
    assert "50MB" in str(e)
```

- [ ] **Step 3: Write config test**

```python
# tests/unit/test_config.py
import os
from emerald.config import get_settings, Settings


def test_settings_default_env():
    s = Settings()
    assert s.emerald_env.value == "development"


def test_settings_from_env():
    os.environ["EMERALD_LOG_LEVEL"] = "DEBUG"
    s = Settings()
    assert s.emerald_log_level == "DEBUG"
    del os.environ["EMERALD_LOG_LEVEL"]
```

- [ ] **Step 4: Run all unit tests**

```bash
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/
git commit -m "test(unit): fill test gaps for registry, exceptions, config"
```

---

## Phase 10: E2E Test

### Task 10.1: Create Seed Script + E2E Test

**Files:**
- Create: `scripts/seed_dev_api_key.py`
- Create: `tests/integration/test_docker_e2e.py`

- [ ] **Step 1: Create seed script**

```python
#!/usr/bin/env python3
"""Seed a development API key for local testing / E2E."""

import asyncio
import sys
from hashlib import sha256

sys.path.insert(0, ".")

from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey
from emerald.models.entity import Entity
from sqlalchemy import select


TEST_KEY = "em_test_00000000000000000000000000000000"


async def main():
    async with session_factory.session() as session:
        # Upsert test entity
        result = await session.execute(
            select(Entity).where(Entity.external_id == "test_entity")
        )
        entity = result.scalar_one_or_none()
        if not entity:
            from uuid import uuid4
            entity = Entity(
                id=uuid4(),
                external_id="test_entity",
                type="user",
                name="Test Entity",
            )
            session.add(entity)
            await session.flush()

        # Check if key exists
        key_hash = sha256(TEST_KEY.encode()).hexdigest()
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if result.scalar_one_or_none():
            print("Dev API key already exists.")
            return

        key = ApiKey(
            entity_id=entity.id,
            key_hash=key_hash,
            key_prefix="em_test_00",
            permissions=["read", "write", "admin"],
            is_active=True,
        )
        session.add(key)
        await session.commit()
        print(f"Created dev API key: {TEST_KEY}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write E2E test**

```python
"""End-to-end test against Docker Compose stack.

Requires: docker compose up -d
Run: pytest tests/integration/test_docker_e2e.py -v
"""

import pytest
import httpx

BASE_URL = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer em_test_00000000000000000000000000000000"}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, headers=HEADERS, timeout=30.0) as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_add_and_search_memory(client):
    # Add
    resp = await client.post("/v1/memories", json={
        "content": "用户喜欢 TypeScript 和函数式编程",
        "entity_id": "e2e_test",
        "content_type": "text",
    })
    assert resp.status_code == 200
    mem_ids = resp.json()["data"]["memory_ids"]
    assert len(mem_ids) > 0

    # Search (semantic — query with different words)
    resp = await client.post("/v1/search", json={
        "q": "JS superset functional",
        "entity_id": "e2e_test",
        "search_mode": "memory",
        "top_k": 5,
    })
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert len(results) > 0
    assert any("TypeScript" in r["content"] for r in results)


@pytest.mark.asyncio
async def test_profile_cache(client):
    # Add memory
    await client.post("/v1/memories", json={
        "content": "用户是资深前端工程师",
        "entity_id": "e2e_profile",
        "content_type": "text",
    })

    # First call (cache miss)
    resp1 = await client.get("/v1/profiles/e2e_profile")
    assert resp1.status_code == 200

    # Second call (cache hit)
    resp2 = await client.get("/v1/profiles/e2e_profile")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["memory_count"] >= 1


@pytest.mark.asyncio
async def test_entity_isolation(client):
    await client.post("/v1/memories", json={
        "content": "Alice 的秘密内容",
        "entity_id": "alice_e2e",
        "content_type": "text",
    })
    await client.post("/v1/memories", json={
        "content": "Bob 的公开内容",
        "entity_id": "bob_e2e",
        "content_type": "text",
    })

    resp = await client.post("/v1/search", json={
        "q": "秘密",
        "entity_id": "bob_e2e",
        "search_mode": "memory",
    })
    results = resp.json()["data"]["results"]
    assert not any("Alice" in r["content"] for r in results)
```

- [ ] **Step 3: Mark E2E test to skip unless explicitly run**

Add to the top of the file or as a pytest marker:

```python
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="Set RUN_E2E=1 to run Docker Compose E2E tests",
)
```

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_dev_api_key.py tests/integration/test_docker_e2e.py
git commit -m "test(e2e): add Docker Compose end-to-end test + dev API key seed script"
```

---

## Phase 11: Coverage, Polish, Release

### Task 11.1: Coverage Audit

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add coverage config**

In `pyproject.toml`:
```toml
[tool.coverage.run]
source = ["emerald"]
omit = ["*/tests/*", "*/migrations/*"]

[tool.coverage.report]
fail_under = 80
skip_covered = false
show_missing = true
```

- [ ] **Step 2: Run full test suite with coverage**

```bash
pytest tests/ --cov=emerald --cov-report=term-missing --cov-fail-under=80
```

If under 80%, identify gaps and write targeted tests.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(coverage): add pytest-cov config with 80% threshold"
```

---

### Task 11.2: README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add status banner and setup instructions**

Add near the top of README:

```markdown
## Status

**Early Access (v0.2.0-alpha)** — Core infrastructure is production-ready. 
Connectors and advanced features are under development.

### Quick Start (Docker Compose)

```bash
git clone https://github.com/.../emerald.git
cd emerald
cp .env.example .env
docker compose up -d
alembic upgrade head
cypher-shell -u neo4j -p emerald_dev -f scripts/init_neo4j.cypher
python scripts/seed_dev_api_key.py
pytest tests/integration/test_docker_e2e.py -v
```

### Known Limitations

- Connectors (Google Drive, GitHub, etc.) are not yet implemented.
- LLM-based relationship classification is rule-based only.
- Reranking and query rewriting are accepted but not yet active.
- Kubernetes deployment templates are planned for v0.3.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): update status to Early Access with Docker setup instructions"
```

---

### Task 11.3: Final Validation

- [ ] **Step 1: Full test run**

```bash
pytest tests/unit/ -x -q
pytest tests/integration/ -x -q
pytest tests/benchmarks/ -x -q
```

All must pass.

- [ ] **Step 2: Docker Compose E2E**

```bash
docker compose down -v
docker compose up -d
sleep 30  # wait for services
alembic upgrade head
cypher-shell -u neo4j -p emerald_dev -f scripts/init_neo4j.cypher
python scripts/seed_dev_api_key.py
RUN_E2E=1 pytest tests/integration/test_docker_e2e.py -v
```

All must pass.

- [ ] **Step 3: Tag and release**

```bash
git tag v0.2.0-alpha
git push origin v0.2.0-alpha
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-infra-hardening.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
