# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] — 2026-06-01

### Added

#### M2 — Full Content Type Support (Phase 3)
- Default extractor/chunker registry factories (`get_default_registry()`) for out-of-the-box content processing
- Comprehensive unit tests for PDF, Image, Audio, and Video extractors with graceful dependency-missing fallback
- URL and Code extractor test coverage expanded to 95%+
- Default registry integration tests verifying all 7 extractors and 5 chunkers are wired correctly

#### M3 — Graph Intelligence (Phase 4+5+7)
- `GraphStore.create_relationship()` for writing EXTENDS and DERIVES_FROM edges to the graph
- `RelationshipEngine` now persists EXTENDS and DERIVES_FROM relationships (was logging-only)
- DERIVES_FROM inference heuristic: new memories combining bigrams from 2+ existing memories trigger derivation
- 16 comprehensive tests for `RelationshipEngine` covering UPDATES atomicity, EXTENDS, DERIVES_FROM, and classification
- 11 tests for `ProfileManager` covering cache hit/miss, compute, static/dynamic facts, and latency (< 100ms)
- 10 tests for `ForgetEngine` covering time-based expiry, noise filtering, episodic decay, and strategy idempotency

#### M5 — API Completeness + SDK
- `DELETE /v1/memories/{id}` endpoint (soft delete — marks as `is_latest=False`)
- API version bumped to `0.3.0` across all surfaces
- SDK tests (25 passing) covering add/search/profile/upload/health/pipeline_status/get_memory

#### Phase 11 — Benchmarks
- Standalone benchmark runner (`scripts/run_benchmarks.py`) with quantitative metrics:
  - Temporal Fact Tracking (LongMemEval-style): accuracy
  - Relationship Classification: accuracy
  - Search Recall (LoCoMo-style): recall
  - MRR (Mean Reciprocal Rank)
  - Profile Computation Latency: cold/warm P50 and P99
  - Conversation Recall (ConvoMem-style): accuracy

#### Phase 12 — Observability
- Prometheus metrics endpoint at `/v1/metrics` via `prometheus-fastapi-instrumentator`

### Fixed
- `PipelineOrchestrator` and `MemoryEngine` now use default registries when none provided (previously created empty registries, causing runtime failures)
- `pipeline/tasks.py` now uses default registries for extract and chunk Celery tasks
- All 484 unit tests now pass (previously 2 tests failed due to missing `OPENAI_API_KEY` in CI)

## [0.2.0] — 2026-05-27

### Added

#### MCP Framework Integration
- MCP Server with `add`, `search`, and `profile` tools
- stdio and SSE transport support
- Docker Compose `mcp` service

#### Pandaria Integration
- HTTP Adapter Spec for Pandaria → Emerald integration
- Phase 2 interaction protocol and Phase 5 MCP setup
- `EmeraldMemoryStore` Rust SDK integration guide

#### v0.2.0 Quickstart Guide
- End-to-end setup documentation for Pandaria team

## [0.1.0] — 2026-05-25

### Added
- **Project skeleton**: FastAPI, SQLAlchemy, Neo4j, Redis, MinIO, Celery
- **Core pipeline**: extract → chunk → embed → index with async Celery chain
- **Text processing**: TextExtractor, TextChunker with sentence/paragraph overlap
- **Code processing**: CodeExtractor with AST-aware splitting via tree-sitter
- **7 extractors**: text, code, pdf, url, image, audio, video
- **5 chunkers**: text, code, markdown, pdf, conversation
- **MemoryEngine**: central orchestrator for content ingestion
- **RelationshipEngine**: rule-based UPDATES/EXTENDS/DERIVES_FROM classification
- **ProfileManager**: two-tier profile (static + dynamic) with Redis caching
- **ForgetEngine**: time expiry, noise filter, episodic decay
- **SearchOrchestrator**: hybrid search (memory + RAG) with query rewriting and reranking
- **REST API**: `POST /v1/memories`, `GET/POST /v1/search`, `GET /v1/profiles/{id}`, `POST /v1/upload`, `GET /v1/health`
- **Python SDK**: `EmeraldClient` with `add`, `search`, `profile`, `upload`
- **Connectors**: GitHub, Google Drive with OAuth and incremental sync
- **Database**: PostgreSQL + pgvector, Neo4j, Alembic migrations
- **Tests**: 400+ tests covering extraction, chunking, search, API, SDK
