# Emerald M1 Completion + M2 Start — Spec

> **Version:** 1.0  
> **Date:** 2026-05-25  
> **Status:** Frozen  
> **Plan:** `docs/superpowers/plans/2026-05-26-m1-completion-m2-start.md`  
> **Scope:** Close the "semantic gap" (mock → real embeddings) and enable file uploads (PDF, image).

---

## 1. Goals & Non-Goals

### 1.1 Goals

1. **Real Semantic Embeddings** — `OpenAIProvider.embed()` calls the real API with tenacity retry; search returns semantically relevant results even when keywords don't overlap.
2. **API Key Authentication** — SHA-256 verification against PostgreSQL `api_keys` table with permission checks and expiry validation.
3. **Health Check Probes** — `/v1/health` reports actual connectivity status of PostgreSQL, Neo4j, Redis, MinIO.
4. **PDF + Image Extraction** — PyMuPDF text extraction and Tesseract OCR return usable text from uploaded files.
5. **File Upload Pipeline** — `POST /v1/upload` stores files in MinIO, creates `Document` records, and submits async Celery task chain.
6. **Celery Task Chain** — `extract → chunk → embed → index → postprocess` tasks execute real business logic, not stubs.
7. **End-to-End Semantic Test** — `add("我喜欢 hiking")` → `search("户外活动")` returns the hiking memory based on real embedding similarity.

### 1.2 Non-Goals

- **Connectors (OAuth / sync / webhooks):** Remain stubbed. Targeted for M2+.
- **Code AST chunking:** Tree-sitter integration is P2; code files fall back to text chunking.
- **Audio/Video extraction:** Remain stubs.
- **Advanced rate limiting:** Fixed-window only; sliding-window deferred.
- **Kubernetes manifests:** Docker Compose remains the only validated deployment target.
- **Reranking & query rewriting:** Parameters accepted but no-ops.

---

## 2. Background

### 2.1 Current State (M1.5 completed)

| Component | Status |
|---|---|
| `GraphStore` | ✅ Neo4j + in-memory fallback |
| `VectorStore` | ✅ pgvector + in-memory fallback; `_pg_vector_literal()` serialization |
| `Neo4j/Redis/PostgreSQL` driver lifecycle | ✅ FastAPI lifespan wired |
| `MockEmbeddingProvider` | ✅ Deterministic hash-based vectors |
| `OpenAIProvider` | ❌ `raise NotImplementedError` |
| `LocalProvider` | ❌ `raise NotImplementedError` |
| `api_key_auth` | ❌ Accepts any `em_*` string |
| `system /health` | ❌ Returns static JSON |
| `upload_file` | ❌ Returns empty payload |
| Celery tasks (5) | ❌ All stubs (`# TODO: Implement`) |
| PDF Extractor | ⚠️ Partial: PyMuPDF text layer only |
| Image Extractor | ⚠️ Partial: OCR with basic preprocessing |
| Alembic 001 migration | ✅ Exists (`35500f582718_initial_schema.py`); 002 misplaced (fixed) |

### 2.2 The Semantic Gap

The entire `SearchOrchestrator` currently operates on **mock embeddings** — vectors derived from SHA-256 hashes of text. Two semantically related sentences ("我喜欢 hiking" and "户外活动偏好") produce completely unrelated vectors. This means:

- `search()` cannot find memories unless keywords literally overlap.
- `RelationshipEngine.infer()` cannot reliably detect semantic similarity between memories.
- The benchmark tests pass, but they measure hash collision, not semantic understanding.

**Closing this gap is the highest priority.** Everything else (file upload, connectors, advanced search) depends on real embeddings.

---

## 3. Architectural Principles (AGENTS.md Constraints)

1. **Memory ≠ RAG.** `search_mode=memory` must traverse the Neo4j graph for temporal validity and personalization; semantic similarity is an optimization layer, not the source of truth.
2. **Graph-first.** Neo4j owns facts, relationships, and temporal metadata. pgvector owns semantic similarity. Both are required, but Neo4j is the primary.
3. **Entity Isolation.** Every query scoped to `entity_id`. No cross-entity leakage.
4. **Graceful Degradation.** Missing `OPENAI_API_KEY` → auto-fallback to `MockEmbeddingProvider` with a warning log. Missing PyMuPDF → `ExtractionError(retryable=False)`.
5. **No Internal API Leakage.** SDK surface remains `add`, `search`, `profile`, `upload`.

### 3.1 Closed Architecture Decisions

The following decisions were raised during spec review and are now **resolved**.

**Decision 1: No `source_type` column on `embeddings` table**

| Option | Rationale | Verdict |
|---|---|---|
| Add `source_type ENUM('memory','document')` | Explicit, self-documenting | Rejected |
| Use `document_id IS NULL` as heuristic | Simpler schema; only two types exist today | **Accepted** |

Memory embeddings (created via `MemoryEngine.add()`) do not supply a `document_id`; RAG/document embeddings (created via upload pipeline) always have one. This implicit discriminator is sufficient until a third source type (e.g., "profile") is introduced. Adding the column now would be premature per YAGNI.

**Decision 2: No `offset` parameter in `VectorStore.search()`**

| Option | Rationale | Verdict |
|---|---|---|
| Add `offset: int = 0` with pagination | Handles pathological cases (entity with thousands of expired memories) | Rejected |
| Static expansion `min(top_k * 5, 100)` | Keeps search latency < 50ms; covers 99% of real-world entity sizes | **Accepted** |

Per AGENTS.md §6, search must be fast. Pagination adds latency and complexity. If an entity has >100 active memories and most top candidates are expired, returning fewer than `top_k` results is acceptable — better than slow pagination. Should this become a real-world issue (e.g., long-lived enterprise agents with 10k+ memories), we can introduce `offset` as a backward-compatible addition.

---

## 4. Module Specifications

### 4.1 Embedding Provider (`emerald/core/embedder.py`)

#### OpenAIProvider

```python
class OpenAIProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI Embedding API with batching and retry.

        - Max 2048 texts per request (OpenAI limit).
        - tenacity: 3 retries, exponential backoff (1s, 2s, 4s).
        - On final failure: raise EmbeddingError.
        """
```

**Batching:** Split `texts` into chunks of ≤ 2048. Call API per chunk. Concatenate results.

**Retry:** Use `tenacity.AsyncRetrying`:
```python
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
import httpx

class EmbeddingRetryableError(Exception):
    """Raised when OpenAI returns a transient error (429, 502, 503, 504)."""
    pass

async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
    response = await self._client.post(
        "/embeddings",
        json={"input": batch, "model": self._model},
    )
    if response.status_code in (429, 502, 503, 504):
        raise EmbeddingRetryableError(f"HTTP {response.status_code}")
    if response.status_code == 401:
        raise AuthenticationError("Invalid OpenAI API key")
    if response.status_code == 400:
        raise ValueError(f"Bad request: {response.text}")
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]

# Retry only on transient HTTP errors
_embed_batch_with_retry = retry(
    retry=retry_if_exception_type(EmbeddingRetryableError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)(_embed_batch)
```

**Auto-fallback in factory:**
```python
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == EmbeddingProviderEnum.openai:
        if settings.openai_api_key:
            return OpenAIProvider(api_key=settings.openai_api_key)
        logger.warning("OpenAI API key missing; falling back to MockEmbeddingProvider")
        return MockEmbeddingProvider(dimension=1536)
    # ... local fallback
```

**Runtime fallback (OpenAI service degradation):**
If the OpenAI API returns persistent 5xx/429 errors *after* tenacity retries are exhausted, the default behaviour is to raise `EmbeddingError` and fail the request. For production deployments that prioritise availability over semantic accuracy, set `EMBEDDING_RUNTIME_FALLBACK=true`. When enabled, `OpenAIProvider.embed()` catches `EmbeddingError` on the final batch, logs a `CRITICAL` alert, and transparently falls back to `MockEmbeddingProvider` for that batch. This ensures ingestion and search continue to work (with degraded relevance) rather than causing a complete outage.

```python
# Inside OpenAIProvider.embed() final catch block
except EmbeddingError as exc:
    if settings.embedding_runtime_fallback:
        logger.critical("embedder.openai.runtime_fallback", error=str(exc))
        fallback = MockEmbeddingProvider(dimension=self.dimension())
        return await fallback.embed(texts)
    raise
```

#### Embedding Cache (Redis)

Cache key: `embedding:{sha256(text + model_name).hexdigest()}`  
Value: JSON-encoded vector  
TTL: 7 days (embeddings are deterministic for a given model + text).

```python
async def _cached_embed(self, texts: list[str]) -> list[list[float]]:
    redis = get_redis_client()
    hashes = [sha256((t + self._model).encode()).hexdigest() for t in texts]
    cached = await redis.mget([f"emb:{h}" for h in hashes])
    
    to_fetch = []
    to_fetch_indices = []
    for i, c in enumerate(cached):
        if c is None:
            to_fetch.append(texts[i])
            to_fetch_indices.append(i)
    
    if to_fetch:
        fetched = await self._embed_batch(to_fetch)
        pipe = redis.pipeline()
        for idx, vec in zip(to_fetch_indices, fetched):
            pipe.setex(f"emb:{hashes[idx]}", 7 * 86400, json.dumps(vec))
        await pipe.execute()
        for idx, vec in zip(to_fetch_indices, fetched):
            cached[idx] = vec
    
    return [json.loads(c) for c in cached]
```

#### Testing

| Test | Description |
|---|---|
| `test_openai_embed_returns_correct_dimension` | "hello" → 1536-dim vector |
| `test_openai_embed_batches_large_input` | 2500 texts → 2 API calls |
| `test_openai_embed_retries_on_timeout` | Mock 502 → retry → success |
| `test_openai_embed_raises_after_max_retries` | Mock 3 failures → `EmbeddingError` |
| `test_cache_hit_skips_api_call` | Second call returns cached vector |
| `test_mock_fallback_when_key_missing` | `OPENAI_API_KEY=""` → `MockEmbeddingProvider` |
| `test_mock_determinism` | Same text → same vector |

---

### 4.1.1 ID Linking Strategy: `memory_id` ↔ `chunk_id`

**Problem:** `MemoryEngine._index()` creates a `memory_id` in Neo4j and independently stores a `chunk_id` in pgvector. `VectorStore.search()` returns `chunk_id`, but `GraphStore.get_memory()` expects `memory_id`. These IDs are unrelated UUIDs, causing search enrichment to always miss.

**Resolution:** The `memory_id` returned by `GraphStore.create_memory()` becomes the canonical ID. `MemoryEngine._index()` assigns this `memory_id` to `chunk.id` before calling `VectorStore.store()`:

```python
# emerald/core/engine.py — MemoryEngine._index()
for chunk, embedding in zip(chunks, embeddings):
    memory_id = await self.graph.create_memory(
        content=chunk.text, entity_id=entity_id, ...
    )
    chunk.id = memory_id  # unify IDs
    await self.vector.store(
        chunk_id=memory_id, text=chunk.text,
        embedding=embedding, entity_id=entity_id, ...
    )
```

This makes `VectorStore.search()` return `memory_id` directly, which `GraphStore.get_memory(memory_id)` can resolve without translation. The `chunk_id` field in the `embeddings` table remains named `chunk_id` for backward compatibility with document chunks (which do use true chunk IDs), but for memory nodes it stores the `memory_id`.

> **Constraint:** Document chunks (RAG path) continue to use real chunk IDs. The memory path uses `memory_id` as `chunk_id`. This is acceptable because `entity_id` + `document_id` distinguish the two use cases in the same table.

> **Implementation note:** `Chunk.id` must be a mutable dataclass field (not a `@property` that regenerates a UUID on every access). The `_index()` method assigns `chunk.id = memory_id` so that downstream pipeline stages (Celery tasks, search enrichment) see a stable, unified identifier.

---

### 4.2 Search Semantic Upgrade (`emerald/core/search.py`)

#### Memory Search Overhaul

Replace keyword-based `_search_memory` with semantic + graph hybrid:

```python
async def _search_memory(self, q: str, entity_id: str, top_k: int) -> list[SearchResult]:
    # 1. Embed query
    query_emb = (await self.embedder.embed([q]))[0]
    
    # 2. Semantic recall from pgvector (broader than top_k for filtering).
    #    Use top_k * 5 to tolerate high expiry/not-latest rates; cap at 100
    #    to avoid unlimited growth for entities with massive memory counts.
    candidate_limit = min(top_k * 5, 100)
    candidates = await self.vector.search(query_emb, entity_id=entity_id, top_k=candidate_limit)
    
    # 3. Enrich with Neo4j metadata and filter
    results = []
    for chunk_id, text, vec_score in candidates:
        mem = await self.graph.get_memory(chunk_id)
        if not mem or not mem.get("is_latest"):
            continue
        if mem.get("valid_until") and mem["valid_until"] < datetime.now(UTC):
            continue
        
        # Blend: vector similarity × confidence
        score = vec_score * mem.get("confidence", 0.5)
        results.append(SearchResult(..., score=score))
    
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
```

> **Rationale:** Neo4j Community lacks vector index. pgvector provides semantic candidate generation; Neo4j provides temporal validity, confidence, and personalization. This is an implementation optimization, not an architectural violation (AGENTS.md §2).

#### Testing

| Test | Description |
|---|---|
| `test_memory_search_semantic_keyword_mismatch` | "户外活动" finds "hiking" memory |
| `test_memory_search_excludes_expired` | Expired memory not in results |
| `test_memory_search_excludes_not_latest` | `is_latest=False` not in results |
| `test_memory_search_entity_isolation` | alice's query doesn't find bob's memories |
| `test_hybrid_merge_deduplicates` | Same content in memory+RAG → one result |

---

### 4.3 API Authentication (`emerald/api/dependencies.py`)

#### api_key_auth

```python
async def api_key_auth(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].startswith("em_"):
        raise HTTPException(401, "Missing or invalid API key")
    
    api_key = parts[1]
    key_hash = sha256(api_key.encode()).hexdigest()
    
    async with session_factory.session() as s:
        result = await s.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True,
            )
        )
        record = result.scalar_one_or_none()
    
    if not record:
        raise HTTPException(401, "Invalid API key")
    
    if record.expires_at and record.expires_at < datetime.now(UTC):
        raise HTTPException(401, "API key expired")
    
    # Fire-and-forget: update last_used_at in background
    # Use asyncio.create_task to avoid blocking the request
    asyncio.create_task(_async_update_last_used(record.id))
    
    request.state.api_key_id = str(record.id)
    request.state.entity_id = str(record.entity_id)
    request.state.permissions = record.permissions
    return "authenticated"
```

#### require_write_permission

```python
async def require_write_permission(request: Request) -> str:
    perms = getattr(request.state, "permissions", [])
    if "write" not in perms and "admin" not in perms:
        raise HTTPException(403, "Write permission required")
    return "authorized"
```

#### Rate Limiting (Redis fixed-window)

```python
async def rate_limit(request: Request):
    key_id = request.state.api_key_id
    endpoint = request.url.path
    limit = RATE_LIMITS.get(endpoint, 60)
    
    current = await redis.incr(f"ratelimit:{key_id}:{endpoint}")
    if current == 1:
        await redis.expire(f"ratelimit:{key_id}:{endpoint}", 60)
    if current > limit:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
```

Applied to: `POST /v1/memories`, `POST /v1/search`, `GET /v1/profiles/{id}`, `POST /v1/upload`.

#### Testing

| Test | Description |
|---|---|
| `test_valid_key_authenticates` | Correct key → 200 |
| `test_invalid_key_returns_401` | Wrong hash → 401 |
| `test_expired_key_returns_401` | `expires_at` in past → 401 |
| `test_readonly_key_cannot_add` | `permissions=["read"]` on POST /memories → 403 |
| `test_rate_limit_returns_429` | 61 requests/min → 429 with Retry-After |
| `test_rate_limit_resets_after_window` | Wait 60s → request succeeds |

---

### 4.4 Health Check (`emerald/api/routes/system.py`)

```python
@router.get("/health")
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

HTTP codes:
- `overall == "ok"` → 200
- `overall == "degraded"` → 200 (body shows degraded services)
- Unhandled exception → 500

#### Testing

| Test | Description |
|---|---|
| `test_health_all_ok` | All services up → status "ok", all checks "ok" |
| `test_health_degraded_when_neo4j_down` | Stop Neo4j → status "degraded", neo4j check shows error |
| `test_health_degraded_when_redis_down` | Stop Redis → status "degraded", redis check shows error |

---

### 4.5 File Upload Pipeline (`emerald/api/routes/upload.py`)

#### Upload Route

```python
@router.post("/upload", status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
) -> dict:
    # 1. Size validation (≤ 50MB)
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise ContentTooLargeError(limit_mb=50, actual=len(contents))
    
    # 2. MIME detection
    detected = content_type or _detect_mime(file.filename)
    
    # 3. MinIO storage
    storage_key = f"{entity_id}/{uuid4().hex}/{file.filename or 'untitled'}"
    await minio_client.put_object(
        bucket, storage_key, io.BytesIO(contents), len(contents),
        content_type=detected,
    )
    
    # 4. Document record
    doc = Document(...)
    async with session_factory.session() as s:
        s.add(doc)
        await s.commit()
    
    # 5. Submit Celery chain
    pipeline_id = await orchestrator.process_async(
        content=contents, content_type=detected, entity_id=entity_id,
        document_id=str(doc.id),
    )
    
    return {
        "data": {
            "document_id": str(doc.id),
            "pipeline_id": pipeline_id,
            "pipeline_status": "queued",
        }
    }
```

#### Pipeline Orchestrator

```python
async def process_async(self, content: str | bytes, *, entity_id: str,
                        content_type: str, document_id: str | None = None) -> str:
    pipeline_id = uuid4().hex
    
    # Insert PipelineJob record
    async with session_factory.session() as s:
        await s.execute(insert(PipelineJob).values(
            id=pipeline_id,
            entity_id=entity_id,
            document_id=document_id,
            content_type=content_type,
            status="queued",
        ))
    
    # Submit Celery chain
    chain(
        extract_task.s(pipeline_id, content, content_type),
        chunk_task.s(),
        embed_task.s(),
        index_task.s(entity_id),
        postprocess_task.s(entity_id),
    ).apply_async()
    
    return pipeline_id
```

#### Testing

| Test | Description |
|---|---|
| `test_upload_creates_document` | Upload PDF → Document record in PG, object in MinIO |
| `test_upload_rejects_oversized_file` | 51MB → 413 ContentTooLargeError |
| `test_upload_returns_pipeline_id` | Response contains pipeline_id with status "queued" |
| `test_pipeline_status_endpoint` | GET /pipelines/{id} → correct status progression |

---

### 4.6 Celery Task Chain (`emerald/pipeline/tasks.py`)

Celery 5.x prefork pool does not support native async. Each task is a **sync function** that creates an isolated event loop via `run_async()`:

```python
# emerald/pipeline/tasks.py
from emerald.async_utils import run_async

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    try:
        return run_async(_run_extract)(pipeline_id, content, content_type)
    except Exception as exc:
        raise self.retry(exc=exc)

async def _run_extract(pipeline_id, content, content_type):
    await init_neo4j()
    try:
        await _update_pipeline_status(pipeline_id, "extracting")
        extractor = ExtractorRegistry().get(content_type)
        result = await extractor.extract(content)
        await redis.setex(f"pipeline:{pipeline_id}:text", 86400, result.text)
        return {"pipeline_id": pipeline_id, "text": result.text}
    except Exception:
        await _update_pipeline_error(pipeline_id, "extracting", str(exc))
        raise
    finally:
        await close_neo4j()
```

Task chain flow:

| Stage | Task | Input | Output | Status |
|---|---|---|---|---|
| 1 | `extract_task` | `content`, `content_type` | `text` | `extracting` |
| 2 | `chunk_task` | `text` | `chunks: list[Chunk]` | `chunking` |
| 3 | `embed_task` | `chunks` | `embeddings: list[list[float]]` | `embedding` |
| 4 | `index_task` | `chunks`, `embeddings`, `entity_id` | `memory_ids` | `indexing` |
| 5 | `postprocess_task` | `memory_ids`, `entity_id` | — | `done` |

**Per-task database connections:** Each task initializes and closes its own Neo4j/SQLAlchemy connections. Connections must not leak across task boundaries (separate processes).

**Inter-task cache TTL:** All intermediate results written to Redis must have a TTL to prevent unbounded growth. Set `ex=86400` (24h) on every pipeline key. The `postprocess_task` deletes keys on success, but TTL guarantees cleanup even if a worker crashes mid-chain.

```python
# In _run_extract, _run_chunk, _run_embed
await redis.setex(f"pipeline:{pipeline_id}:text", 86400, result.text)
await redis.setex(f"pipeline:{pipeline_id}:chunks", 86400, json.dumps(chunks_data))
await redis.setex(f"pipeline:{pipeline_id}:embeddings", 86400, json.dumps(embeddings))
```

#### Testing

| Test | Description |
|---|---|
| `test_extract_task_runs_extractor` | Input PDF bytes → extracted text in result |
| `test_chunk_task_splits_text` | Input text → list of chunks with metadata |
| `test_embed_task_generates_vectors` | Input chunks → embeddings with correct dimension |
| `test_index_task_writes_to_graph_and_vector` | Input chunks+embeddings → Neo4j + pgvector records |
| `test_postprocess_task_infers_relationships` | Input memory_ids → RelationshipEngine.infer() called |
| `test_task_retry_on_failure` | Simulated exception → task retries 3 times |
| `test_pipeline_status_transitions` | Status sequence: queued → extracting → ... → done |

---

### 4.7 PDF Extractor (`emerald/pipeline/extraction/pdf.py`)

```python
class PDFExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ExtractionError(..., retryable=False)
        
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise ExtractionError(..., retryable=False)
        
        text_parts = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{text}")
            else:
                # Image-only page: attempt OCR
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                ocr_text = await self._ocr_fallback(img_bytes)
                text_parts.append(f"[Page {page_num + 1}]\n{ocr_text}")
        
        doc.close()
        full_text = "\n\n".join(text_parts)
        return ExtractedContent(text=full_text, content_type="pdf",
                                 metadata={"page_count": len(text_parts)})
```

> **Note:** OCR fallback requires `Pillow` and `pytesseract`. If unavailable, image-only pages are marked `(OCR unavailable)`.

#### Testing

| Test | Description |
|---|---|
| `test_pdf_extracts_text` | Multi-page PDF → text with page markers |
| `test_pdf_ocr_fallback` | Scanned PDF → OCR text extracted |
| `test_pdf_missing_pymupdf` | ImportError → ExtractionError(retryable=False) |
| `test_pdf_corrupted` | Invalid bytes → ExtractionError(retryable=False) |

---

### 4.8 Image Extractor (`emerald/pipeline/extraction/image.py`)

```python
class ImageExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            raise ExtractionError(..., retryable=False)
        
        try:
            img = Image.open(io.BytesIO(content))
            # Preprocess: grayscale → denoise → threshold
            gray = img.convert("L")
            # Simple denoise: median filter
            denoised = gray.filter(ImageFilter.MedianFilter(size=3))
            # Adaptive threshold
            thresh = denoised.point(lambda x: 0 if x < 128 else 255, "1")
            
            try:
                text = pytesseract.image_to_string(thresh, lang="chi_sim+eng")
            except pytesseract.TesseractError:
                text = pytesseract.image_to_string(thresh, lang="eng")
            conf = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
            avg_conf = sum(conf["conf"]) / len(conf["conf"]) if conf["conf"] else 0
            
            return ExtractedContent(
                text=text,
                content_type="image",
                metadata={
                    "ocr_confidence": avg_conf,
                    "image_size": img.size,
                },
            )
        except Exception as e:
            raise ExtractionError(..., retryable=False)
```

#### Testing

| Test | Description |
|---|---|
| `test_image_ocr_extracts_text` | PNG with text → extracted text |
| `test_image_missing_tesseract` | ImportError → ExtractionError(retryable=False) |
| `test_image_corrupted` | Invalid bytes → ExtractionError(retryable=False) |

---

## 5. Data Flow

### 5.1 Text Ingestion (Sync Path)

```
client.add("我喜欢周末去山里 hiking", entity_id="user_1")
  ↓
POST /v1/memories  →  api_key_auth()  →  MemoryEngine.add()
  ↓
TextExtractor.extract()  →  TextChunker.chunk()
  ↓
EmbeddingProvider.embed()  →  [Redis cache check]  →  OpenAI API (or Mock)
  ↓
GraphStore.create_memory()  →  Neo4j: MERGE Entity + CREATE Memory
VectorStore.store()  →  PostgreSQL/pgvector INSERT
  ↓
RelationshipEngine.infer()  →  Neo4j: classify + CREATE UPDATES/EXTENDS
ProfileManager.invalidate()  →  Redis: DEL profile:{entity_id}
```

### 5.2 File Upload (Async Path)

```
client.upload("report.pdf", entity_id="user_1")
  ↓
POST /v1/upload  →  size check  →  MinIO put_object()
  ↓
PostgreSQL: INSERT INTO documents
PipelineOrchestrator.process_async()
  ↓
PostgreSQL: INSERT INTO pipeline_jobs (status='queued')
Celery: chain(extract, chunk, embed, index, postprocess).apply_async()
  ↓
Worker process:
  extract_task  →  PDFExtractor  →  Redis: cache extracted text
  chunk_task    →  TextChunker   →  Redis: cache chunks
  embed_task    →  OpenAI embed  →  Redis: cache embeddings
  index_task    →  GraphStore + VectorStore  →  Neo4j + pgvector
  postprocess   →  RelationshipEngine + ProfileManager.invalidate
  ↓
PostgreSQL: UPDATE pipeline_jobs SET status='done'
```

### 5.3 Search

```
client.search("户外活动偏好", entity_id="user_1", mode="hybrid")
  ↓
POST /v1/search
  ↓
EmbeddingProvider.embed(["户外活动偏好"])  →  query vector
  ↓
mode=memory:
  VectorStore.search(query_vec)  →  candidate chunk_ids (min(top_k * 5, 100))
  GraphStore.get_memory() per candidate  →  filter is_latest, valid_until
  Blend score: vec_similarity × confidence
  ↓
mode=rag:
  VectorStore.search(query_vec)  →  document chunks
  ↓
mode=hybrid:
  Run both, deduplicate by content, sort by score, return top_k
```

---

## 6. Interface Changes

### 6.1 New Files

| File | Purpose |
|---|---|
| *(none — 001 `35500f582718_initial_schema.py` already exists)* | — |
| `scripts/seed_dev_api_key.py` | Bootstrap a test API key for local development |
| `emerald/api/routes/pipelines.py` | `GET /v1/pipelines/{id}` endpoint |
| `tests/integration/test_embedder_integration.py` | OpenAI embedder with real API (or skip) |
| `tests/integration/test_auth_integration.py` | API key auth + rate limiting |
| `tests/integration/test_upload_integration.py` | File upload → MinIO → pipeline |
| `tests/integration/test_celery_pipeline.py` | Celery task chain execution |
| `tests/integration/test_docker_e2e.py` | Single end-to-end test |

### 6.2 Modified Files

| File | Changes |
|---|---|
| `emerald/core/embedder.py` | Implement `OpenAIProvider.embed()`; add caching wrapper; auto-fallback logic |
| `emerald/core/search.py` | Replace keyword memory search with semantic + Neo4j hybrid |
| `emerald/core/profile.py` | Wire Redis cache with `use_db` flag; in-memory dict remains as test fallback |
| `emerald/api/dependencies.py` | Real SHA-256 auth + permission checks + rate limiting |
| `emerald/api/routes/system.py` | Real health probes for all services |
| `emerald/api/routes/upload.py` | Full MinIO + PG + Celery integration |
| `emerald/pipeline/orchestrator.py` | Implement `process_async` with PG job tracking |
| `emerald/pipeline/tasks.py` | Real Celery task implementations |
| `emerald/pipeline/extraction/pdf.py` | OCR fallback for image-only pages |
| `emerald/pipeline/extraction/image.py` | Preprocessing pipeline (grayscale → denoise → threshold) |

### 6.3 No-Change Files

| File | Rationale |
|---|---|
| `emerald/sdk/client.py` | Public surface unchanged |
| `emerald/api/schemas/*.py` | Request/response models stable |
| `emerald/core/relationship.py` | Rule-based logic sufficient |
| `emerald/core/forget.py` | Logic sound; Celery Beat wiring only |
| `emerald/pipeline/chunking/*.py` | Already implemented |
| `emerald/pipeline/celery.py` | Already configured with broker, backend, Beat schedule, autodiscover |

---

## 7. Test Specifications

### 7.1 Coverage Targets

| Module | Line | Branch |
|---|---|---|
| `emerald/core/` | ≥ 90% | ≥ 80% |
| `emerald/api/` | ≥ 85% | ≥ 75% |
| `emerald/pipeline/` | ≥ 85% | ≥ 75% |
| `emerald/sdk/` | ≥ 90% | ≥ 80% |
| **Overall** | **≥ 80%** | **≥ 70%** |

### 7.2 New Unit Tests

| Test File | Cases | Key Scenarios |
|---|---|---|
| `tests/unit/test_embedder.py` | 10 | OpenAI batching, retry (502/503/504), no-retry (400/401), raises after max retries, cache hit/miss, mock fallback, determinism |
| `tests/unit/test_search_semantic.py` | 8 | Semantic recall, expired exclusion, not-latest exclusion, entity isolation, hybrid dedup, score blending, empty results, keyword mismatch |
| `tests/unit/test_auth.py` | 10 | Valid key, invalid key, expired key, missing header, malformed header, readonly on write, admin on all endpoints, rate limit hit, rate limit reset, no bypass |
| `tests/unit/test_health.py` | 5 | All ok, degraded (each service), all down, unknown exception |
| `tests/unit/test_pdf_extractor.py` | 5 | Text extraction, OCR fallback, missing dep, corrupted, empty page |
| `tests/unit/test_image_extractor.py` | 4 | OCR extraction, missing dep, corrupted, language fallback |

### 7.3 New Integration Tests

| Test File | Cases | Requirements |
|---|---|---|
| `tests/integration/test_embedder_integration.py` | 3 | Real OpenAI API key (or skip); semantic similarity verification; cache persistence |
| `tests/integration/test_auth_integration.py` | 6 | PostgreSQL running; api_keys table seeded; rate limit reset |
| `tests/integration/test_upload_integration.py` | 4 | MinIO + PostgreSQL + Celery worker running; oversized rejection |
| `tests/integration/test_celery_pipeline.py` | 8 | Celery worker with `memory://` broker; all 5 stages; retry; failure paths |
| `tests/integration/test_docker_e2e.py` | 1 | Full Docker Compose stack |

### 7.4 E2E Test Scenario

```python
async def test_full_docker_e2e():
    """
    1. Seed dev API key.
    2. Add text memory → verify Neo4j + pgvector.
    3. Search with semantic mismatch → verify real embedding recall.
    4. Get profile → verify Redis cache hit on second call.
    5. Upload PDF → verify MinIO object, pipeline completion, searchability.
    6. Verify entity isolation.
    """
```

---

## 8. Acceptance Criteria

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
- [ ] Coverage ≥ 80% line, ≥ 70% branch.
- [ ] README updated with setup instructions including OpenAI API key configuration.

---

## 9. Implementation Plan (4 Weeks)

### Pre-Week 1 Blocker: Database Schema

| Day | Task |
|---|---|
| 0 | Verify full migration chain (001 `35500f582718` → 002 pgvector → 003 `content_type`) on fresh PostgreSQL. **Unblocks all database-dependent tasks.** |

### Week 1: Embedder + Search

| Day | Task |
|---|---|
| 1 | Implement `OpenAIProvider.embed()` with batching + tenacity retry |
| 2 | Add embedding cache (Redis); implement `get_embedding_provider()` auto-fallback |
| 3 | Refactor `SearchOrchestrator._search_memory` → semantic + Neo4j hybrid |
| 4 | Write embedder unit tests + integration tests |
| 5 | Write search semantic tests; verify E2E semantic recall |

### Week 2: Auth + Health + Upload

| Day | Task |
|---|---|
| 6 | Implement `api_key_auth` with SHA-256 + permission checks |
| 7 | Implement rate limiting (Redis fixed-window) |
| 8 | Implement real health check probes |
| 9 | Implement upload route: MinIO + Document record + pipeline submission |
| 10 | Write auth, health, upload tests |

### Week 3: Celery Pipeline Core

| Day | Task |
|---|---|
| 11 | Implement `PipelineOrchestrator.process_async` with PG job tracking |
| 12 | Verify Celery app config (`emerald/pipeline/celery.py`) and wire stub tasks into Beat schedule |
| 13 | Implement `extract_task` and `chunk_task` |
| 14 | Implement `embed_task` and `index_task` |
| 15 | Implement `postprocess_task`; wire Celery Beat schedule |

### Week 4: Extractors + Testing + Polish

| Day | Task |
|---|---|
| 16 | Enhance PDF extractor with OCR fallback |
| 17 | Enhance image extractor with preprocessing pipeline |
| 18 | Write Celery pipeline integration tests |
| 19 | Write Docker Compose E2E test |
| 20 | Coverage audit + gap filling |
| 21 | PDF/Image extractor tests |
| 22 | Error path audit; structured logging verification |
| 23 | README update; API docs sync |
| 24 | Final review + merge |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenAI API key not available in CI | High | Medium | Auto-fallback to Mock; integration tests skip when no key |
| Celery async complexity | Medium | High | `run_async()` helper; extensive integration testing |
| PyMuPDF / Tesseract not installed | Medium | Low | Graceful `ExtractionError`; CI installs deps |
| pgvector index build time | Low | Low | `ef_construction=64` for dev |
| Multi-service integration flaky | Medium | Medium | Docker Compose health checks; test retry loops |
| OpenAI API cost in CI / dev loops | Medium | Medium | Dev default = MockProvider; real API only in integration tests with explicit opt-in |

---

**End of Spec**
