# Emerald M1.5 — Infrastructure Hardening Spec

> **Version:** 1.0  
> **Date:** 2026-05-25  
> **Status:** Draft → Pending Approval  
> **Scope:** Transform all in-memory stubs into production-grade database-driven implementations.

---

## 1. Goals & Non-Goals

### 1.1 Goals (Must-Have)

1. **Real Persistence Layer:** Neo4j, PostgreSQL/pgvector, Redis, and MinIO are fully wired into the business logic. `use_db=False` remains as a test-only fallback.
2. **Semantic Hybrid Search:** Memory search uses pgvector cosine similarity + Neo4j temporal filtering; RAG uses pgvector HNSW; hybrid mode deduplicates and merges both streams.
3. **Async Celery Pipeline:** File upload triggers a real Celery chain (extract → chunk → embed → index → postprocess) with PostgreSQL `pipeline_jobs` state tracking.
4. **Production Auth:** API Key SHA-256 verification against PostgreSQL `api_keys` table, with permission checks (`read`/`write`/`admin`) and expiry validation.
5. **Redis-Backed Profiles:** Profile cache lives in Redis with active invalidation on ingest; target < 100ms for cached reads.
6. **Real Health Checks:** `/v1/health` probes all downstream services and reports degraded states truthfully.
7. **Structured Observability:** Every pipeline stage emits JSON logs with the schema defined in `docs/architecture/pipeline.md` §8.1.
8. **Test Hardening:** Coverage ≥ 80% (line), `emerald/core/` ≥ 90%; Docker Compose E2E test passes end-to-end.

### 1.2 Non-Goals (Out of Scope)

- **Connectors (OAuth / sync / webhooks):** Remains stubbed. Targeted for M2.
- **LLM-based relationship classification:** The rule-based `RelationshipEngine` stays; LLM augmentation is a future enhancement.
- **Multi-model embedding migration:** Only one active embedding model at a time. Model-switching re-indexing strategy is documented but not implemented.
- **Kubernetes manifests:** Docker Compose is the only validated deployment target for M1.5.
- **Reranking & query rewriting:** The `rerank` and `rewrite_query` parameters are accepted but may remain no-ops.

---

## 2. Background: Current State

| Component | Current | Target |
|---|---|---|
| `GraphStore` | In-memory `dict[entity_id, list[dict]]` | Neo4j async driver |
| `VectorStore` | In-memory `dict[chunk_id, embedding]` | pgvector `vector()` + HNSW |
| `ProfileManager` | In-memory `dict` cache | Redis cache |
| `EmbeddingProvider` | `MockEmbeddingProvider` only | `OpenAIProvider` (with auto-fallback to Mock) |
| `SearchOrchestrator._search_memory` | Keyword token overlap | pgvector semantic + Neo4j filtering |
| Celery tasks | Stubs (`# TODO`) | Real task chain with retry |
| Upload endpoint | Returns empty payload | MinIO → PG → Celery chain |
| API Key auth | Accepts any `em_*` string | SHA-256 verify against `api_keys` table |
| Health check | Hard-coded `"ok"` | Live probes of all services |

---

## 3. Architectural Principles (AGENTS.md Constraints)

The following are **non-negotiable** for every change in this spec:

1. **Memory ≠ RAG.** `search_mode=memory` must traverse the Neo4j graph; it must not silently fall back to vector search.
2. **Graph-first.** The source of truth for facts, relationships, and temporal validity is Neo4j. pgvector is an optimization layer for semantic similarity.
3. **Atomic UPDATES.** When a fact is superseded, a single Neo4j transaction must: (a) set `old.is_latest = false`, (b) set `old.replaced_by = new.id`, (c) create `(new)-[:UPDATES]->(old)`.
4. **Entity Isolation.** Every database query (Neo4j, pgvector, Redis) must be scoped to `entity_id`. Cross-entity leakage is a P0 bug.
5. **No Internal API Leakage.** The public SDK surface remains `add`, `search`, `profile`, `upload`. No graph-level operations are exposed.
6. **Graceful Degradation.** Optional dependencies (PyMuPDF, Tesseract, Whisper) missing → `ExtractionError(retryable=False)` without crashing the pipeline.
7. **Declarative Defaults.** Developers do not configure chunk size, embedding model, or relationship rules. The system chooses intelligently.

---

## 4. Module Specifications

### 4.1 Neo4j GraphStore (`emerald/core/graph.py`)

#### Interface Changes

`GraphStore.__init__` signature remains backward-compatible:

```python
class GraphStore:
    def __init__(self, use_db: bool = True) -> None:
        ...
```

When `use_db=True` (new default), it initializes `neo4j.AsyncGraphDatabase.driver(...)` from `Settings.neo4j_uri` / `neo4j_user` / `neo4j_password`. When `use_db=False`, the existing in-memory `_memories` dict is used.

#### Methods

| Method | Behavior (use_db=True) | Error Handling |
|---|---|---|
| `create_memory(...)` | `session.run()` with Cypher `MERGE (e:Entity {id: $entity_id}) ON CREATE SET e.created_at = datetime(), e.type = "user" CREATE (m:Memory {...}) CREATE (e)-[:HAS_MEMORY]->(m)` | `EmeraldError` on connection/auth failure |
| `get_memory(id)` | `session.run("MATCH (m:Memory {id: $id}) RETURN m")` | Returns `None` if not found |
| `list_latest_memories(entity_id, limit, memory_type)` | `MATCH (e)-[:HAS_MEMORY]->(m) WHERE m.is_latest AND (m.valid_until IS NULL OR m.valid_until > now()) RETURN m ORDER BY m.created_at DESC LIMIT $limit` | Returns `[]` for unknown entity |
| `update_is_latest(id, is_latest, replaced_by)` | `MATCH (m {id: $id}) SET m.is_latest=$il, m.replaced_by=$rb, m.updated_at=datetime()` | Idempotent |
| `create_relationship(...)` (new) | Cypher `CREATE (a)-[r:UPDATES|EXTENDS|DERIVES_FROM]->(b)` | Atomic transaction |

#### Schema Assumptions

The Neo4j instance must have these constraints (applied via `scripts/init_neo4j.cypher`):

```cypher
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;
CREATE INDEX memory_latest FOR (m:Memory) ON (m.is_latest, m.memory_type);
CREATE INDEX memory_temporal FOR (m:Memory) ON (m.valid_until);
```

`Entity` nodes are **upserted** atomically within the same transaction as `Memory` creation. The driver lifecycle is managed via FastAPI lifespan:

```python
# emerald/db/neo4j.py
_async_driver: neo4j.AsyncDriver | None = None

async def init_neo4j() -> None:
    global _async_driver
    settings = get_settings()
    _async_driver = neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _async_driver.verify_connectivity()

async def close_neo4j() -> None:
    global _async_driver
    if _async_driver:
        await _async_driver.close()
        _async_driver = None

def get_neo4j_driver() -> neo4j.AsyncDriver:
    if _async_driver is None:
        raise RuntimeError("Neo4j driver not initialized. Call init_neo4j() first.")
    return _async_driver
```

Registered in `emerald/api/app.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from emerald.db.neo4j import init_neo4j
    from emerald.db.redis import init_redis
    await init_neo4j()
    await init_redis()
    yield
    await close_neo4j()
    await close_redis()
```

#### Testing

- **Unit:** `GraphStore(use_db=False)` retains all existing tests.
- **Integration:** A new `tests/integration/test_neo4j_graph.py` spins up a test Neo4j container (via `testcontainers` or a fixture-managed Docker container) and verifies CRUD, temporal filtering, and atomic UPDATES.

---

### 4.2 pgvector VectorStore (`emerald/core/vector.py`)

#### Interface Changes

```python
class VectorStore:
    def __init__(self, use_db: bool = True) -> None:
        ...
```

`use_db=True` connects via SQLAlchemy async session to PostgreSQL. `use_db=False` retains the existing in-memory store.

#### Schema

The existing Alembic migration `35500f582718_initial_schema.py` defines `embeddings.embedding` as `postgresql.JSONB`, which cannot be directly cast to `vector`. A **new migration** must replace the column:

```python
# migrations/versions/002_add_pgvector_embedding.py
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_column("embeddings", "embedding")
    op.add_column(
        "embeddings",
        sa.Column("embedding", Vector(1536), nullable=False),
    )
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

> **Note:** We intentionally use `ef_construction=64` for faster index builds during development. Production tuning is documented for M2+.

> **Note:** We intentionally use `ef_construction=64` for faster index builds during development. Production tuning is documented for M2+.

#### Methods

| Method | SQL / Behavior |
|---|---|
| `store(chunk_id, text, embedding, entity_id, ...)` | `INSERT INTO embeddings (chunk_id, text, embedding, entity_id, ...) VALUES (...)` |
| `search(query_embedding, entity_id, top_k)` | `SELECT chunk_id, text, 1 - (embedding <=> $query) AS score FROM embeddings WHERE entity_id = $eid ORDER BY embedding <=> $query LIMIT $top_k` |

The cosine similarity score returned by pgvector `1 - (a <=> b)` is normalized to `[0, 1]`.

#### Testing

- `tests/unit/test_vector_store.py` tests both in-memory and DB modes.
- Integration tests verify exact-match recall (same text → score ≈ 1.0) and entity isolation.

---

### 4.3 Embedding Provider (`emerald/core/embedder.py`)

#### Auto-Fallback Strategy

`get_embedding_provider()` factory logic:

```python
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()

    if settings.embedding_provider == EmbeddingProviderEnum.openai:
        if settings.openai_api_key:
            return OpenAIProvider(api_key=settings.openai_api_key, model=...)
        logger.warning("OpenAI API key missing; falling back to MockEmbeddingProvider")
        return MockEmbeddingProvider(dimension=1536)

    if settings.embedding_provider == EmbeddingProviderEnum.local:
        return LocalProvider(...)

    # Default fallback
    return MockEmbeddingProvider(dimension=1536)
```

#### OpenAIProvider Implementation

```python
class OpenAIProvider(EmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Batch into max 2048 texts per request
        # Retry with tenacity: 3 attempts, exponential backoff
        # Raise EmbeddingError on final failure
```

- **Batching:** OpenAI supports up to 2048 texts per request. We split large batches internally.
- **Retry:** `tenacity` or `httpx` retries with exponential backoff (1s, 2s, 4s).
- **Timeout:** 30s per batch.
- **Dimension:** 1536 for `text-embedding-3-small`, 3072 for `text-embedding-3-large`.

#### Embedding Cache (Redis)

A new `CachedEmbeddingProvider` wrapper (or inline logic in `MemoryEngine._embed`):

```python
text_hash = sha256(text.encode()).hexdigest()
cached = await redis.get(f"embedding:{text_hash}")
if cached:
    return json.loads(cached)
# ... fetch from provider ...
await redis.setex(f"embedding:{text_hash}", 7*24*3600, json.dumps(embedding))
```

Cache TTL: 7 days. Cache invalidation is unnecessary because embeddings are deterministic for a given model + text.

#### Testing

- `tests/unit/test_embedder.py`:
  - Mock embedder determinism
  - OpenAI provider batch splitting
  - Cache hit/miss behavior (using fakeredis or a test Redis container)

---

### 4.4 Redis-Backed ProfileManager (`emerald/core/profile.py`)

#### Interface

No breaking changes to `ProfileManager.get(entity_id)` or `.invalidate(entity_id)`.

#### Internal Behavior

```python
class ProfileManager:
    def __init__(self, graph: GraphStore | None = None, redis: Redis | None = None):
        self.graph = graph or GraphStore()
        self.redis = redis or get_redis_client()
        self._ttl = 24 * 3600  # 24h

    async def get(self, entity_id: str) -> EntityProfile:
        cached = await self.redis.get(f"profile:{entity_id}")
        if cached:
            return EntityProfile.parse_raw(cached)  # or json.loads

        profile = await self.compute(entity_id)
        await self.redis.setex(
            f"profile:{entity_id}",
            self._ttl,
            profile.json(),
        )
        return profile

    async def invalidate(self, entity_id: str) -> None:
        await self.redis.delete(f"profile:{entity_id}")
```

The in-memory `_cache` dict is **removed**. `ProfileManager` always uses Redis in production and a test-safe `fakeredis` or dict fallback in unit tests.

#### Testing

- Unit tests use `fakeredis.aioredis` (or a simple dict shim if fakeredis is unavailable).
- Verify cache hit latency < 5ms and cache miss latency < 100ms (with in-memory graph).

---

### 4.5 Hybrid Search (`emerald/core/search.py`)

#### Memory Search Overhaul

Current `_search_memory` uses naive keyword overlap. New implementation:

```python
async def _search_memory(self, q: str, entity_id: str, top_k: int, filters: dict | None) -> list[SearchResult]:
    # 1. Generate query embedding
    query_embedding = (await self.embedder.embed([q]))[0]

    # 2. Semantic recall from pgvector (memories are also stored as embeddings)
    semantic_hits = await self.vector.search(query_embedding, entity_id=entity_id, top_k=top_k * 2)

    # 3. Temporal & confidence filtering via Neo4j
    results = []
    for chunk_id, text, vec_score in semantic_hits:
        memory = await self.graph.get_memory(chunk_id)
        if not memory or not memory["is_latest"]:
            continue
        if memory.get("valid_until") and memory["valid_until"] < now:
            continue
        if filters and not self._passes_filters(memory, filters):
            continue

        # Blend score: vector similarity * confidence
        score = vec_score * memory.get("confidence", 0.5)
        results.append(SearchResult(..., score=score))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
```

> **Why store memory embeddings in pgvector?** Because `Memory` nodes in Neo4j Community Edition do not natively support vector indexes. We dual-write: Neo4j owns the graph structure and temporal metadata; pgvector owns the semantic similarity.
>
> **AGENTS.md Principle #1 compliance:** `search_mode=memory` traverses the Neo4j graph for filtering, temporal validity, and relationship weighting. The initial candidate set is generated via pgvector semantic similarity, but all personalization logic (entity scoping, `is_latest`, `valid_until`, confidence blending) is applied by Neo4j. This is an implementation detail, not an architectural violation — the semantic index is a performance optimization, not the source of truth.

#### RAG Search

`_search_rag` remains largely unchanged but now queries the real pgvector table for document chunks (not memory nodes). The entity filter is applied.

#### Merge & Deduplicate

`_merge_results` continues to deduplicate by normalized content and sort by score. A new enhancement: if the same content appears in both memory and RAG, the memory result (higher personalization) takes priority.

#### Testing

- `tests/core/test_search.py` updated to use real embedder + real stores (via test containers).
- Assert that semantic queries return results even when keywords don't overlap (e.g., query "JS superset" returns "TypeScript is a superset of JavaScript").

---

### 4.6 Celery Pipeline (`emerald/pipeline/orchestrator.py`, `tasks.py`, `celery.py`)

#### Orchestrator

`process_async` must now:

1. Compute `content_hash = sha256(content).hexdigest()`.
2. Insert a `PipelineJob` record into PostgreSQL with `status='queued'`.
3. Submit a Celery chain:
   ```python
   chain(
       extract_task.s(pipeline_id, content, content_type),
       chunk_task.s(),
       embed_task.s(),
       index_task.s(entity_id),
       postprocess_task.s(entity_id),
   ).apply_async()
   ```
4. Return `pipeline_id`.

#### Task Implementations

All Celery task bodies are **synchronous** (Celery 5.x prefork pool does not support native async tasks). Each task creates an isolated event loop via `asyncio.run()` and opens/closes its own database connections inside that loop:

```python
# emerald/async_utils.py
import asyncio
from functools import wraps

def run_async(coro_func):
    """Run an async function inside a fresh event loop."""
    @wraps(coro_func)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper
```

```python
# emerald/pipeline/tasks.py
from emerald.async_utils import run_async
from emerald.db.neo4j import init_neo4j, close_neo4j
from emerald.db.session import async_session

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    return _run_extract(pipeline_id, content, content_type)

@run_async
async def _run_extract(pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    await init_neo4j()
    try:
        await _update_pipeline_status(pipeline_id, "extracting")
        extractor = ExtractorRegistry().get(content_type)
        result = await extractor.extract(content)
        await _cache_set(f"pipeline:{pipeline_id}:extracted", result.text)
        return {"pipeline_id": pipeline_id, "content_type": content_type}
    except Exception as exc:
        await _update_pipeline_error(pipeline_id, "extracting", str(exc))
        raise exc
    finally:
        await close_neo4j()
```

> **Important:** Database connections (Neo4j driver, SQLAlchemy engine, Redis) are initialized and torn down **inside each task**. They must not be shared across task boundaries because Celery prefork workers run in separate processes.

#### Pipeline Status Tracking

Each task updates `pipeline_jobs.status` in PostgreSQL:

| Task | Status |
|---|---|
| Before extract | `extracting` |
| Before chunk | `chunking` |
| Before embed | `embedding` |
| Before index | `indexing` |
| After postprocess | `done` |
| On final failure | `failed` |

#### Postprocess Task

```python
@app.task
def postprocess_task(prev_result: dict, entity_id: str) -> None:
    pipeline_id = prev_result["pipeline_id"]
    memory_ids = prev_result.get("memory_ids", [])

    # 1. Relationship inference
    rel_engine = RelationshipEngine()
    asyncio.run(rel_engine.infer(memory_ids, entity_id))

    # 2. Profile cache invalidation
    profile_mgr = ProfileManager()
    asyncio.run(profile_mgr.invalidate(entity_id))

    # 3. Cleanup Redis temp keys
    for key in ["extracted", "chunks", "embeddings"]:
        redis.delete(f"pipeline:{pipeline_id}:{key}")

    update_pipeline_status(pipeline_id, "done")
```

#### Testing

- Use `pytest-celery` or a test Celery worker with an in-memory broker (`memory://`) for fast unit tests.
- Docker Compose E2E test verifies a real file upload flows through all 5 stages and ends in `status=done`.

---

### 4.7 Upload Endpoint (`emerald/api/routes/upload.py`)

#### Full Implementation

```python
@router.post("/upload", status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
) -> dict:
    # 1. Validate size (<= 50MB)
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise ContentTooLargeError(limit_mb=50, actual=len(contents))

    # 2. Detect content_type from filename if not provided
    detected = content_type or detect_mime(file.filename)

    # 3. Upload to MinIO
    import io
    storage_key = f"{entity_id}/{uuid4().hex}/{file.filename or 'untitled'}"
    await minio_client.put_object(
        settings.minio_bucket,
        storage_key,
        io.BytesIO(contents),
        len(contents),
        content_type=detected,
    )

    # 4. Create Document record in PostgreSQL
    doc_id = uuid4()
    await db.execute(
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

    # 5. Submit async pipeline
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
```

> **Note:** `pipeline_jobs` requires a new migration to add `content_type` column:
> ```python
> op.add_column("pipeline_jobs", sa.Column("content_type", sa.String(50)))
> ```

#### Pipeline Status Endpoint

```python
@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_status(pipeline_id: str) -> dict:
    row = await db.fetch_one(
        select(PipelineJob).where(PipelineJob.id == pipeline_id)
    )
    if not row:
        raise HTTPException(404, "Pipeline not found")
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

---

### 4.8 API Key Authentication (`emerald/api/dependencies.py`)

#### Implementation

```python
async def api_key_auth(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer em_"):
        raise HTTPException(401, "Missing or invalid API key")

    api_key = auth_header.removeprefix("Bearer ")
    key_hash = sha256(api_key.encode()).hexdigest()

    async with async_session() as session:
        result = await session.execute(
            select(ApiKey)
            .where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        )
        key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(401, "Invalid API key")

    if key_record.expires_at and key_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "API key expired")

    # Update last_used_at (fire-and-forget via Celery to avoid blocking)
    update_last_used.delay(str(key_record.id))

    request.state.entity_id = str(key_record.entity_id)
    request.state.permissions = key_record.permissions
    request.state.api_key_id = str(key_record.id)
    return "authenticated"

async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(403, "Write permission required")
    return "authorized"
```

#### Rate Limiting (Redis)

A new dependency `rate_limit_dependency` uses Redis **fixed-window** counters (sliding-window requires Sorted Sets and is deferred to M2):

```python
async def rate_limit_dependency(request: Request):
    key_id = request.state.api_key_id
    endpoint = request.url.path
    limit = RATE_LIMITS.get(endpoint, 60)
    window = 60

    current = await redis.incr(f"rate_limit:{key_id}:{endpoint}")
    if current == 1:
        await redis.expire(f"rate_limit:{key_id}:{endpoint}", window)
    if current > limit:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(window)})
```

> **Future:** True sliding-window rate limiting will be implemented in M2 using Redis Sorted Sets.

Applied selectively to `POST /v1/memories`, `POST /v1/search`, `GET /v1/profiles/{id}`, `POST /v1/upload`.

---

### 4.9 Health Check (`emerald/api/routes/system.py`)

#### Real Probes

```python
@router.get("/health")
async def health_check() -> dict:
    checks = {}
    overall = "ok"

    # PostgreSQL
    try:
        async with async_session() as s:
            await s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall = "degraded"

    # Neo4j
    try:
        driver = get_neo4j_driver()
        await driver.verify_connectivity()
        checks["neo4j"] = "ok"
    except Exception as e:
        checks["neo4j"] = f"error: {e}"
        overall = "degraded"

    # Redis
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall = "degraded"

    # MinIO
    try:
        await minio_client.list_buckets()
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"error: {e}"
        overall = "degraded"

    # Celery (lightweight broker check with timeout)
    try:
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

HTTP status code mapping:
- `overall == "ok"` → 200
- `overall == "degraded"` → 200 (with degraded checks in body; services are partially available)
- Unhandled exception → 500

---

## 5. Data Flow Specifications

### 5.1 Ingestion (Text)

```
client.add("用户喜欢 TypeScript", entity_id="user_123")
  │
  ▼
POST /v1/memories
  │
  ▼
api_key_auth() ──► PostgreSQL api_keys table (SHA-256 verify)
  │
  ▼
MemoryEngine.add()
  │
  ├──► ExtractorRegistry ──► TextExtractor.extract()
  │
  ├──► ChunkerRegistry ──► TextChunker.chunk()
  │
  ├──► EmbeddingProvider.embed() ──► Redis cache check ──► OpenAI API (or Mock fallback)
  │
  ├──► GraphStore.create_memory() ──► Neo4j: MERGE Entity + CREATE Memory + HAS_MEMORY
  │   │   (source of truth — must succeed for pipeline to continue)
  │
  ├──► VectorStore.store() ──► PostgreSQL/pgvector INSERT
  │   │   (best-effort; failure logged but does not abort pipeline)
  │
  ├──► RelationshipEngine.infer() ──► Neo4j: classify + CREATE UPDATES/EXTENDS
  │
  └──► ProfileManager.invalidate() ──► Redis: DEL profile:{entity_id}
```

#### Cross-Database Consistency Strategy

Neo4j and PostgreSQL have no distributed transaction coordinator. The pipeline adopts a **Neo4j-primary, pgvector-eventually-consistent** model:

1. **Phase 4 (Indexing)** writes to Neo4j first. If Neo4j fails, the entire pipeline retries.
2. **Phase 4 then writes to pgvector.** If pgvector fails, the pipeline records the error in `pipeline_jobs.error_message` but continues to `status=done`. The memory is fully functional via graph search; it simply lacks a vector index for semantic recall.
3. **Background repair:** A scheduled Celery task (`repair_missing_embeddings`) periodically scans `pipeline_jobs` for completed jobs with `error_message` containing "pgvector" and re-attempts the embedding write. This is a P1 follow-up, not required for M1.5.
4. **Search graceful degradation:** If `mode=memory` and a memory node has no corresponding pgvector row, the keyword-based fallback (existing token-overlap scorer) is used as a last resort. This ensures no memory is ever unsearchable.

### 5.2 Ingestion (File / Async)

```
client.upload("report.pdf", entity_id="user_123")
  │
  ▼
POST /v1/upload ──► api_key_auth() + require_write_permission()
  │
  ▼
Upload route
  ├──► Validate size (<= 50MB)
  ├──► MinIO: put_object()
  ├──► PostgreSQL: INSERT INTO documents
  └──► PipelineOrchestrator.process_async()
         │
         ├──► PostgreSQL: INSERT INTO pipeline_jobs (status='queued')
         └──► Celery: chain(extract_task, chunk_task, embed_task, index_task, postprocess_task)
```

### 5.3 Search

```
client.search("TypeScript", entity_id="user_123", mode="hybrid")
  │
  ▼
POST /v1/search
  │
  ▼
SearchOrchestrator.search()
  │
  ├── mode=memory ──► EmbeddingProvider.embed([q])
  │                    VectorStore.search() ──► pgvector semantic recall
  │                    GraphStore.get_memory() ──► Neo4j temporal/confidence filter
  │
  ├── mode=rag ──► EmbeddingProvider.embed([q])
  │                 VectorStore.search() ──► pgvector (document chunks only)
  │
  └── mode=hybrid ──► Run both paths
                      Merge, deduplicate by content
                      Sort by score desc
                      Return top_k
```

### 5.4 Profile Read

```
client.profile("user_123")
  │
  ▼
GET /v1/profiles/user_123
  │
  ▼
ProfileManager.get()
  │
  ├──► Redis: GET profile:user_123 ──► Cache HIT ──► return (~50ms)
  │
  └──► Cache MISS
         ├──► GraphStore.list_latest_memories() ──► Neo4j
         ├──► Compute static + dynamic facts
         ├──► Redis: SETEX profile:user_123 (TTL=24h)
         └──► return
```

---

## 6. Interface Change Summary

### 6.1 New Files

| File | Purpose |
|---|---|
| `emerald/db/neo4j.py` | `AsyncDriver` factory + connection health check |
| `emerald/db/redis.py` | `aioredis` client factory (was stub, now real) |
| `emerald/db/minio.py` | MinIO client factory (was stub, now real) |
| `emerald/db/session.py` | SQLAlchemy async session factory (was stub, now real) |
| `emerald/async_utils.py` | `run_async(coro)` helper for sync Celery tasks |
| `tests/integration/test_docker_e2e.py` | Full Docker Compose E2E test |
| `tests/integration/test_neo4j_graph.py` | Neo4j-specific integration tests |

### 6.2 Modified Files

| File | Changes |
|---|---|
| `emerald/core/graph.py` | Add Neo4j driver branch; keep in-memory fallback |
| `emerald/core/vector.py` | Add pgvector branch; keep in-memory fallback |
| `emerald/core/embedder.py` | Implement `OpenAIProvider`; add caching wrapper |
| `emerald/core/search.py` | Replace keyword memory search with semantic + Neo4j |
| `emerald/core/profile.py` | Replace dict cache with Redis; remove in-memory cache |
| `emerald/core/engine.py` | Wire real stores; no interface changes |
| `emerald/pipeline/orchestrator.py` | Implement `process_async` with PG job tracking |
| `emerald/pipeline/tasks.py` | Real Celery task implementations |
| `emerald/api/dependencies.py` | Real auth + rate limiting |
| `emerald/api/routes/upload.py` | Full MinIO + PG + Celery integration |
| `emerald/api/routes/system.py` | Real health probes |
| `migrations/versions/` | Add pgvector extension + HNSW index migration |

### 6.3 No-Change Files (Contract Stability)

| File | Rationale |
|---|---|
| `emerald/sdk/client.py` | Public SDK surface is unchanged; only the server-side behavior changes |
| `emerald/api/schemas/*.py` | Request/response models are stable |
| `emerald/core/relationship.py` | Rule-based logic is sufficient; no schema changes |
| `emerald/core/forget.py` | Logic is sound; only the caller (Celery Beat) needs wiring |
| `emerald/pipeline/extraction/*.py` | Extractors are already implemented with graceful degradation |
| `emerald/pipeline/chunking/*.py` | Chunkers are already implemented |

---

## 7. Test Specifications

### 7.1 Test Infrastructure

- **Neo4j test container:** Use `testcontainers.neo4j.Neo4jContainer` (or a pytest fixture that starts `neo4j:5-community` via Docker SDK) for integration tests.
- **PostgreSQL test container:** Use `testcontainers.postgres.PostgresContainer` with `pgvector/pgvector:pg16` image.
- **Redis test:** Use `fakeredis.aioredis` for unit tests; optional test container for integration.
- **Celery test:** Use `celery.contrib.testing` with `memory://` broker for fast unit tests.

### 7.2 New Tests to Write

#### Unit Tests (no external services)

| Test File | Count | Coverage Target |
|---|---|---|
| `tests/unit/test_embedder.py` | 8 | OpenAI batching, retry, cache hit/miss, Mock determinism |
| `tests/unit/test_graph_store.py` | 10 | CRUD, temporal filter, atomic update, entity isolation (in-memory mode) |
| `tests/unit/test_vector_store.py` | 8 | Store/search, cosine similarity, entity isolation, top_k (in-memory mode) |
| `tests/unit/test_extractor_registry.py` | 5 | Register, get, unsupported, fallback, overwrite |
| `tests/unit/test_chunker_registry.py` | 5 | Same patterns |
| `tests/unit/test_exceptions.py` | 6 | Hierarchy, retryable flags, message formatting |
| `tests/unit/test_config.py` | 4 | Env loading, defaults, validation |

#### Integration Tests (requires Docker services)

| Test File | Count | Coverage Target |
|---|---|---|
| `tests/integration/test_neo4j_graph.py` | 10 | Real Neo4j CRUD, constraint validation, UPDATES atomicity |
| `tests/integration/test_pgvector.py` | 8 | Real pgvector insert/search, HNSW index usage, cosine accuracy |
| `tests/integration/test_redis_cache.py` | 6 | Profile cache set/get/invalidate, TTL expiry |
| `tests/integration/test_auth.py` | 6 | Key validation, expiry, permissions, rate limiting |
| `tests/integration/test_celery_pipeline.py` | 6 | Task chain execution, retry, status transitions |
| `tests/integration/test_docker_e2e.py` | 1 | **The single E2E test that validates the entire system** |

#### E2E Test Scenario

```python
async def test_full_docker_e2e():
    """
    1. Bootstrap a dev API key via scripts/seed_dev_api_key.py.
    2. Add text memory -> verify in Neo4j + pgvector.
    3. Search -> verify semantic recall (not just keyword).
    4. Get profile -> verify Redis cache hit on second call.
    5. Upload a small PDF -> verify MinIO object exists, pipeline job created,
       Celery chain completes, document searchable.
    6. Verify entity isolation: entity A's data not in entity B's search.
    """
```

**API Key Bootstrap:** The E2E test requires a valid API key in the `api_keys` table. A helper script `scripts/seed_dev_api_key.py` creates a test key:

```python
# scripts/seed_dev_api_key.py
import asyncio
from emerald.db.session import async_session
from emerald.models.api_key import ApiKey

async def main():
    async with async_session() as session:
        key = ApiKey(
            entity_id=...,  # upsert test entity
            key_hash=sha256(b"em_test_00000000000000000000000000000000").hexdigest(),
            key_prefix="em_test_00",
            permissions=["read", "write", "admin"],
            is_active=True,
        )
        session.add(key)
        await session.commit()

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.3 Coverage Targets

| Module | Line Coverage | Branch Coverage |
|---|---|---|
| `emerald/core/` | ≥ 90% | ≥ 80% |
| `emerald/pipeline/` | ≥ 85% | ≥ 75% |
| `emerald/api/` | ≥ 85% | ≥ 75% |
| `emerald/sdk/` | ≥ 90% | ≥ 80% |
| `emerald/db/` | ≥ 70% | — |
| **Overall** | **≥ 80%** | **≥ 70%** |

---

## 8. Acceptance Criteria (Definition of Done)

A checklist that must **all pass** before M1.5 is declared complete:

- [ ] `docker compose up -d` starts all 8 services without error.
- [ ] `alembic upgrade head` applies all migrations successfully on a fresh PostgreSQL instance.
- [ ] `scripts/init_neo4j.cypher` constraints and indexes are applied.
- [ ] `pytest tests/unit/ -x` passes in < 10s with no external services.
- [ ] `pytest tests/integration/ -x` passes against the Docker Compose stack.
- [ ] `pytest tests/benchmarks/ -x` passes (performance regressions flagged).
- [ ] `POST /v1/memories` with text persists to Neo4j and is retrievable via `GET /v1/memories/{id}`.
- [ ] `POST /v1/search` with `mode=memory` returns semantically relevant results even when keywords don't overlap.
- [ ] `GET /v1/profiles/{id}` returns in < 100ms on second call (Redis cache hit).
- [ ] `POST /v1/upload` accepts a 1MB PDF, stores it in MinIO, creates a `pipeline_jobs` record, and the Celery worker processes it to `done`.
- [ ] `GET /v1/health` reports degraded if any downstream service is stopped.
- [ ] Invalid API key returns HTTP 401; expired key returns HTTP 401; read-only key on `POST /v1/memories` returns HTTP 403.
- [ ] Rate limiting returns HTTP 429 with `Retry-After` header after exceeding the threshold.
- [ ] Entity isolation: `alice`'s memories never appear in `bob`'s search results (verified by E2E test).
- [ ] Overall test coverage (pytest-cov) ≥ 80% line, ≥ 70% branch.
- [ ] README updated with "Alpha → Early Access" status and accurate setup instructions.

---

## 9. Implementation Plan (6 Weeks)

### Week 1: Database Layer Foundation

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 1 | Neo4j async driver factory + lifespan integration (`emerald/db/neo4j.py`, `api/app.py`) | Dev | Driver connects on startup, closes on shutdown |
| 2 | `GraphStore(use_db=True)` implementation | Dev | All methods backed by Neo4j; in-memory fallback preserved |
| 3 | SQLAlchemy async session factory (`emerald/db/session.py`) | Dev | Async session context manager works |
| 4 | pgvector `VectorStore(use_db=True)` + Alembic migration | Dev | Store + cosine search working; migration applies cleanly |
| 5 | Redis client factory (`emerald/db/redis.py`) + ProfileManager migration | Dev | Profile cache uses Redis; fakeredis for tests |
| 6 | Integration tests for Neo4j + pgvector + Redis | Dev | `tests/integration/test_neo4j_graph.py`, `test_pgvector.py`, `test_redis_cache.py` |

### Week 2: Embedding & Search Hardening

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 7 | `OpenAIProvider.embed()` with batching + retry | Dev | Real API calls succeed; mock fallback when no key |
| 8 | Embedding cache (Redis) + `async_utils.py` | Dev | Cache hit/miss tests pass; `run_async()` wrapper ready |
| 9 | Refactor `SearchOrchestrator._search_memory` to use pgvector + Neo4j | Dev | Semantic memory search replaces keyword search |
| 10 | Hybrid search merge logic refinement + search integration tests | Dev | Deduplication rules tested; semantic recall verified |
| 11 | Buffer / contingency | Dev | Catch-up for Week 1–2 spillover |

### Week 3: Celery Pipeline Core

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 12 | `PipelineOrchestrator.process_async` + PG job tracking | Dev | Jobs inserted with correct status |
| 13 | `extract_task` + `chunk_task` Celery implementations | Dev | Tasks execute and update PG status |
| 14 | `embed_task` + `index_task` Celery implementations | Dev | Dual-write to Neo4j + pgvector from worker |
| 15 | `postprocess_task` + Celery Beat schedule validation | Dev | Relationship inference + profile invalidation from worker |
| 16 | Buffer / Celery integration testing | Dev | Task retry and failure paths tested |

### Week 4: Upload, Auth, & Health

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 17 | MinIO client integration + `upload_file` route | Dev | Files stored in MinIO; Document records created |
| 18 | `GET /v1/pipelines/{id}` endpoint + `content_type` migration | Dev | Returns real pipeline job status |
| 19 | API Key SHA-256 auth + permission checks | Dev | `api_key_auth` queries PG; `require_write_permission` enforced |
| 20 | Redis fixed-window rate limiting | Dev | 429 responses with Retry-After |
| 21 | Real health check probes | Dev | `/v1/health` reflects actual service states |

### Week 5: Test Hardening

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 22 | Unit test缺口: embedder, graph, vector, registry, exceptions, config | Dev | 30+ new unit tests |
| 23 | Integration tests: auth, Celery pipeline | Dev | `test_auth.py`, `test_celery_pipeline.py` |
| 24 | Docker Compose E2E test + `seed_dev_api_key.py` | Dev | `test_docker_e2e.py` passes end-to-end |
| 25 | Coverage audit + gap filling | Dev | Coverage ≥ 80% line, ≥ 70% branch |
| 26 | Benchmark regression check | Dev | No performance regressions vs. in-memory baseline |

### Week 6: Polish & Documentation

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 27 | Error path audit: all `except` blocks log structured JSON | Dev | Log schema compliance verified |
| 28 | README update: Alpha → Early Access, accurate setup, known limitations | Dev | PR-ready README |
| 29 | API docs sync: OpenAPI spec matches implemented routes | Dev | `openapi.yaml` updated |
| 30 | Docker Compose validation on clean machine | Dev | Fresh clone → `docker compose up` → E2E passes |
| 31 | Buffer / final fixes | Dev | Unplanned issues |

### Week 7: Release

| Day | Task | Owner | Deliverable |
|---|---|---|---|
| 32–34 | Final code review, merge to main | Dev | Clean merge |
| 35 | Tag `v0.2.0-alpha`, write release notes | Dev | Git tag + GitHub release |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **OpenAI API key is a dev barrier** | High | Medium | Auto-fallback to `MockEmbeddingProvider` when key is missing; CI uses Mock |
| **Neo4j / pgvector Docker startup slow** | Medium | Low | Retain `use_db=False` for fast unit tests; integration tests use fixtures with retry loops |
| **Celery task async complexity** | Medium | High | Standardize on `run_async()` helper; extensive integration testing |
| **pgvector HNSW index build time** | Medium | Low | Use `ef_construction=64` for dev; document production tuning |
| **Embedding dimension mismatch** | Low | High | `embeddings.dimensions` column stored per row; table `vector(N)` set to max supported model |
| **Rate limiting false positives** | Low | Medium | Conservative limits (60/min for memories); monitor before tightening |
| **Redis connection failure in tests** | Medium | Low | `fakeredis` fallback for unit tests; testcontainers for integration |

---

## 11. Appendix: Configuration Reference

### Required Environment Variables (Production)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
NEO4J_URI=bolt://host:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=***
REDIS_URL=redis://:pass@host:6379/0

# Celery
CELERY_BROKER_URL=redis://:pass@host:6379/1
CELERY_RESULT_BACKEND=redis://:pass@host:6379/2

# Storage
MINIO_ENDPOINT=host:9000
MINIO_ACCESS_KEY=***
MINIO_SECRET_KEY=***
MINIO_BUCKET=emerald-documents

# Embedding
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-***
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Security
API_KEY_SECRET=***
ENCRYPTION_KEY=***  # 64 hex chars
```

### Development Defaults (Zero-Config)

If the above are omitted, `Settings` falls back to Docker Compose local addresses. If `OPENAI_API_KEY` is empty, embedding falls back to `MockEmbeddingProvider`.

---

## 12. Decision Log

| # | Decision | Rationale | Date |
|---|---|---|---|
| 1 | **Bottom-up implementation (Week 1–2 DB layer, then search, then pipeline)** | Establishes stable foundations before building features on top | 2026-05-25 |
| 2 | **Neo4j AsyncDriver + in-memory fallback** | Native async support; fallback preserves fast unit tests | 2026-05-25 |
| 3 | **OpenAI default with auto-fallback to Mock** | Lowers developer onboarding barrier; Mock available for CI | 2026-05-25 |
| 4 | **Memory embeddings dual-written to pgvector** | Neo4j lacks native vector index; pgvector provides semantic recall for memory search | 2026-05-25 |
| 5 | **Celery task bodies are sync calling async helpers** | Celery 5.x async task support is experimental; `run_async()` is the stable pattern | 2026-05-25 |
| 6 | **HNSW `ef_construction=64` for dev** | Faster index builds; production tuning (200+) documented but deferred | 2026-05-25 |
| 7 | **Rate limiting via Redis, not in-memory** | Required for multi-instance API deployment | 2026-05-25 |
| 8 | **Neo4j-primary / pgvector-eventually-consistent** | No distributed transaction coordinator; Neo4j is source of truth, pgvector failure is non-fatal | 2026-05-25 |
| 9 | **Memory search uses pgvector for candidate generation** | Neo4j Community lacks vector index; semantic recall is an optimization layer, not a source-of-truth violation | 2026-05-25 |
| 10 | **Celery task DB connections are per-task lifecycle** | Prefork workers run in separate processes; connections must not leak across task boundaries | 2026-05-25 |

---

**End of Spec**
