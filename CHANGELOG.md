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

## [Unreleased] — Post-v0.3.0 (2026-06-02 to 2026-06-21)

> **状态：** 33 commits after v0.3.0 release。未作为 v0.4.0 发布（需要 M1 实施完成后升版本号）。详见 [`docs/roadmap.md`](docs/roadmap.md) 与 [`docs/superpowers/plans/2026-06-21-m1-v0.4.0-implementation.md`](docs/superpowers/plans/2026-06-21-m1-v0.4.0-implementation.md)。

### Added

#### M3 — Graph Intelligence 补齐
- **LLM 事实提取** (`emerald/pipeline/chunking/fact_extractor.py`)：DeepSeek V4-Flash 驱动的多事实分解、类型分类（fact/preference/episodic）、置信度评分、summary 生成
- **图谱搜索遍历** (`emerald/core/search.py:_expand_relationships`)：沿 EXTENDS / DERIVES_FROM 关系双向深度=1 遍历，`expansion_factor=0.85`
- **首选项强化** (`emerald/core/engine.py:_strengthen_preferences`)：重复偏好 +0.05 置信度（上限 0.95）
- **关系推断 LLM 化** (`emerald/core/relationship.py`)：DeepSeek 优先，OpenAI 降级
- **语义去重** (`emerald/core/engine.py:_check_duplicate`)：bigram 快速过滤 + LLM 边界判定
- **多因子画像评分** (`emerald/core/profile.py:_compute_importance`)：置信度 35% + 时近性 25% + 类型 20% + 关系 20%

#### API 增强
- `POST /v1/memories/batch` — 批量写入（最多 50 条）
- `GET /v1/graph/viewport` — 图谱可视化（节点+边）
- MongoDB 风格元数据过滤：`$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne`
- 查询改写 LLM 化：DeepSeek 语义扩展替代模式匹配

#### 本地嵌入
- **fastembed 支持** (`emerald/core/embedder.py`)：ONNX runtime，无 PyTorch 依赖，完全离线运行

#### 生产基础设施
- `ReconciliationEngine` (`emerald/core/reconciliation.py`)：后台修复 Neo4j 孤立节点（双写一致性补偿）
- Redis 分布式锁 (`emerald/core/lock.py`)：防止 Celery Beat 多实例并发执行
- Neo4j 生产配置：连接池 50、超时 30s、重试 30s
- CORS 生产加固：环境变量区分 wildcard 与严格模式
- `GraphStore.update_memory_confidence()`：原子置信度更新
- `GraphStore.get_related_memories()`：双向关系遍历
- `GraphStore.list_entity_ids()`：修复 ForgetEngine 生产环境失效

#### 基准测试
- 升级至 6 维度评估（Fact Recall / Temporal Updates / Relationship Class / Profile Accuracy / Distractor Resist / Forgetting Correctness）
- 对齐 LongMemEval / LoCoMo / ConvoMem 三大公开基准
- `scripts/run_benchmarks.py` 从 ~250 行扩展到 1154 行
- JSON 报告自动生成到 `reports/benchmark-YYYYMMDD-HHMMSS.json`
- `reports/` 已添加至 `.gitignore`

#### 文档
- `docs/comparison-supermemory.md` v2 重写（495 行）：对比矩阵完整反转——三项 P0 致命差距中两项已修复
- `docs/roadmap.md`：post-v0.3.0 战略路线图（4 主题、5 里程碑 v0.4-v0.8、依赖驱动、不锁死时间）
- `docs/superpowers/plans/2026-06-21-m1-v0.4.0-implementation.md`：M1 (v0.4.0) 实施计划（2228 行，TDD bite-sized 任务）
- 删除本地 `_references/supermemory-main` 仓库引用

### Fixed
- 异步阻塞修复：`emerald/api/routes/v1/upload.py` 改用 `asyncio.to_thread` 包裹 MinIO 同步调用
- 5 个测试失败修复：tracing、code chunker、API route leakage
- CORS 配置生产加固（移除硬编码 `allow_origins=["*"]`）
- stdlib logging 误用 structlog 关键字参数导致 OTel 缺失时导入崩溃
- `pipeline/tasks.py` 改用默认 registry 以避免空 registry 运行时失败
- 移除 dead code `raw_content_ref`，改进 dedup 归一化
- 恢复 `ConversationChunker.__init__` 中 `FactExtractor` 注入（在 merge 中丢失）
- `engine.add()` 与 `pipeline/tasks.py` 全面异步化
- 所有 chunker `chunk()` 方法统一改为 `async def`

### Test Coverage
- 测试函数定义数：537 → **601**（+64，+12%）
- 重点新增：
  - `tests/pipeline/test_fact_extractor.py`（11 tests，DeepSeekFactExtractor）
  - `tests/pipeline/test_semantic_text_chunker.py`（6 tests）
  - `tests/pipeline/test_conversation_chunker.py`（+49 tests）
  - `tests/unit/test_lock.py`（Redis 锁）
  - `tests/unit/test_reconciliation.py`（双写一致性）
  - `tests/unit/test_embedder.py`（fastembed）
  - `tests/core/test_search.py`（+193 行图谱遍历测试）
- 5 个测试失败 → 全部修复

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
