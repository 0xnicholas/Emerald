# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **结构化数据（JSON/CSV）分块与自动检测**（spec issue #1）：
  - 新增 `json`/`csv` 分块器——JSON 按顶层结构（数组元素/对象键）分块，小元素合并为有界批次；CSV 每块携带表头，行按字符上限分批；畸形输入（JSON 解析失败、CSV 字段数不一致）记录 warning 并回退到 text 分块，不阻断管线。
  - `content_type` 缺省时自动嗅探：可解析为 dict/list 的 JSON、分隔符与字段数（逐行校验）一致的 CSV 走结构化分块；显式声明（含显式 `text`）永远优先，现有显式调用行为不变。
  - 结构化块携带来源元数据（记录索引/键/行范围），随记忆存入图谱（`chunk_source` 命名空间，不覆盖调用方 metadata），检索结果可溯源到原始记录。
  - MIME → 管线内容类型解析（`emerald/pipeline/mime.py`）：上传与外部源携带的 `application/json`、`text/csv`、`application/pdf` 等 MIME 字符串正确解析到短类型，修复了此前上传路径在提取阶段即失败的问题。
  - `.json`/`.csv` 文件扩展名加入上传 MIME 检测。
  - 默认提取器/分块器注册表加入 `json`/`csv`；注册表断言测试同步更新（README 承诺 vs 实现的持续守卫）。

### Tests

- **嵌入模型参数化与双模型两列报告**（issue #18，T2）— 真实嵌入基准支持按参数选模型，双模型对照落地：
  - `scripts/run_benchmarks.py` 新增 `--embedding-model`（默认 `text-embedding-3-small`，未指定时行为与现状一致走 provider factory）；显式指定时直接构造对应 `OpenAIProvider`，维度自动映射（3-small → 1536、3-large → 3072）并写入 JSON 报告 `config.embedding_dim`，下游不再猜维度。
  - `scripts/benchmark_to_markdown.py` 新增双模式：`--dual --small <json> [--large <json>] --output <md>` 渲染每维度 3-small / 3-large 两列 + 差值（Δ）；`--large` 缺失（某模型跑失败）时该列以 — 呈现并显式告警，不整体崩溃；单报告模式输出与旧版字节一致（CI mock 路径不受影响）。
  - `scripts/run_real_benchmarks.sh` 依次跑 3-small、3-large 两次并合并渲染 `docs/benchmarks/real-llm-results.md`；3-large 失败时回退单列报告继续完成，DeepSeek LLM 关系分类流程保持不变。
  - 渲染层单元测试（`tests/benchmarks/test_benchmark_to_markdown.py`）：两列都存在 / 单列缺失 / 单模型缺维度 / 旧报告无 `embedding_model` 字段 / CLI 双模式与单模式兼容；CLI 选型测试（`tests/benchmarks/test_run_benchmarks_cli.py`）：3-large→3072、3-small→1536、默认走 factory、mock 不受影响。

- **独立侧质量套件**（ADR-0001，roadmap M2）— `tests/quality/temporal/` 三 section + CI 聚合门（workflow `quality-temporal`）：
  - **时序正确性**（ticket #9）：25 更新链取代 + 20 时间过期 + 12 显式冲突分流 + 10 保留用例；4 指标聚合门——取代正确率 ≥99%、过期抑制率 ≥99%、保留正确率 ≥98%、分流准确率 ≥95%。冲突分流覆盖高影响（internal_type=decision → PENDING_CONFLICT）与低影响（自动 UPDATES）双路径及 keep_old/keep_new/keep_both/manual 四种 resolve 动作。
  - **遗忘有效性**（ticket #10）：噪音过滤（25 旧噪音 + 5 近期保留）、情节衰减（20 旧 episodic 归档，图谱瘦身率 50–90% 区间断言）、噪音注入对抗语料两档（50% 与 80% 噪音比，各 60 条）、信号保留（引擎全链路 12 信号，清理后检索保持率）。4 指标聚合门——噪音清除率 ≥95%、信号存活率 ≥98%（误删 ≤2%）、检索保持率 ≥95%、瘦身率区间。
  - **图谱关系精度**（ticket #11）：61 例标注语料类型判定（25 UPDATES / 18 EXTENDS / 18 NONE）、20 例方向与语义、原子性不变量扫描（UPDATES 边 ⟺ target 归档且 replaced_by 指向 source，违规 =0）、跨实体隔离（图关系 + 检索双向断言）。4 指标聚合门——类型判定 ≥95%、方向 ≥98%、原子性违规 =0%、泄漏 =0%。
  - 确定性语料 + mock 嵌入 + 规则路径（`use_llm=False`）；Neo4j 真实存储变体（`test_neo4j_quality_variants.py`，不可达时 skip，CI 聚合门在 compose 服务下覆盖 Cypher 分支）。三节指标各自全绿才通过聚合门，互不抵消。
- **fix(graph): in-memory `create_update_relation` 缺少 source 存在性检查** — 质量套件原子性场景发现：Cypher 分支以 `MATCH (new)` 守卫缺失 source 的更新为 no-op，in-memory 分支却仍会归档 target（幻影归档）。已补齐存在性检查，两后端行为一致。
- **fix(tests): `test_pipeline_tasks` 顺序依赖** — forget 类任务测试依赖真实 Neo4j driver loop（`_neo4j_driver_for_loop`），全量套件按目录顺序运行时行为不一致。已 mock driver loop，单元测试不再依赖外部服务。

- **路由枚举适配 Starlette 1.x 惰性路由**（issue #2）— `include_router` 在 Starlette 1.x 下注册惰性 `_IncludedRouter`（无 `path` 属性），`app.routes` 简单过滤得到空集。`tests/api/test_route_completeness.py` 与 `tests/negative/test_no_internal_exposure.py` 改为递归展开惰性路由（`effective_candidates()`），在无引擎 stub 与有引擎两种形态下枚举实际路由面；v2 泄漏守卫从恒真断言修复为真实前缀检查。同步重新生成 `docs/api/openapi.yaml`（含 sources/spaces/extract-url 路由与 memories 的 patch/delete 方法），OpenAPI 漂移测试回归绿，`generate_openapi.py --check` 通过。
- **清理过期 API 测试**（issue #3）— v0.4.0 下线 v2 路由后残留的 v2 断言（`test_api_versioning.py` 三处、`test_upload_authorization.py` 一处）改为断言 v2 返回 404 或删除；`/v1/files` 测试从偏移分页（`page`）签名迁移到游标分页（`page_token` + `page_size`），断言新响应结构（`pagination.next_page_token`/`has_more`），新增无效游标 token → 422 行为测试。产品路由代码零改动。
- **矛盾链对抗场景（第 7 维度）**（issue #17，T1）— 基准套件新增 Contradiction Chain 维度，补足 Temporal Updates 的深度覆盖：
  - `scripts/run_benchmarks.py` 新增第 7 个场景函数 `benchmark_contradiction_chain`（与现有场景同构：同签名、同 `BenchResult` 返回）：5 条链 × 5 轮连续取代（6 步/链），每轮构造对同一事实的完全矛盾新事实（结构模板换填充 / 数值变更 / 矛盾措辞三类语料，规则分类器在 mock 下确定性输出 UPDATES）。
  - 每轮验证四件事：旧事实 `is_latest` 翻转为 False 且 `replaced_by` 指向新事实、UPDATES 边从新事实指向旧事实、最新事实按精确文本查询命中 top-1、过期事实不再被召回。指标：`latest_recall@1` / `expired_exclusion_rate` / `is_latest_flip_rate` / `update_relation_rate` / `overall_accuracy`（mock 下全部 1.0，无 API 依赖）。
  - 报告链路接入：JSON 报告（7 维度）与 `benchmark_to_markdown.py` 渲染（含双模型对照模式的每维度列）均包含该维度得分与通过状态。
  - 单元测试（`tests/benchmarks/test_memory_benchmarks.py` 新增 `TestContradictionChain`）：5 轮取代后 is_latest 翻转与 replaced_by 链、召回正确性（最终事实 top-1、过期事实排除）、每轮恰好一条 UPDATES 边、场景函数在 mock 嵌入下确定性（四项指标 == 1.0）。
- **双门槛评估纯函数**（issue #19，T3）— 绝对分报告的双门槛判定落地为无 IO 纯函数：
  - `scripts/benchmark_gates.py` 新增 `evaluate_gates(report, mock_baseline) -> GateResults`：发布门槛（每维真实分数 ≥ 对应 mock 基线）与通过门槛（矛盾链 ≥ 80% 且 7 维等权均分 ≥ 70%，等权默认）独立判定，互不掩盖；维度分数取与报告表格一致的 key metric（复用 `_pick_key_metric`），门槛结论与读者在报告中看到的分数同源。
  - 维度集合不一致、缺矛盾链维度、维度无可比指标时抛 `GateEvaluationError` 并指明维度；两门槛均为 ≥ 语义（恰好 0.8 / 恰好 0.7 即通过）。
  - mock 基线获取：`load_mock_baseline()` 默认读库内已入库的 `docs/benchmarks/mock-baseline.json`（已生成入库，含全部 7 维度；`reports/` 被 gitignore 不能作基线）；缺文件 / 非法 JSON / 缺 `results` 列表均有明确报错与指引。
  - CLI：`python scripts/benchmark_gates.py <report.json> [--baseline <mock.json>]` 输出两门槛逐维结论，退出码 0/1/2（双通过 / 门槛失败 / 评估错误），可接入发布流程。
  - 单元测试（`tests/benchmarks/test_benchmark_gates.py`，25 例）：双通过 / 单维低于基线 / 基线侧与报告侧缺维度 / 缺 results / 缺矛盾链 / 无可比指标 / 非对象条目 / metrics 为空 / 维度重名 / 两侧选中指标不一致 / 临界分边界（矛盾链恰好 0.8 通过、均分恰好 0.7 通过、0.699 不通过，均分比较带 1e-9 浮点容差）/ 基线加载错误路径 / CLI 退出码与 --json 输出。
  - 文档同步：`docs/roadmap.md` 双门槛公式由过时的「6 维加权均分」更正为 #16/#19 决议的「7 维等权均分 ≥ 70%」（等权默认）；`_pick_key_metric` 升为公共 `pick_key_metric`（跨脚本契约）。
- **绝对分报告落地接线与 README 死链修复**（issue #20，T4）— 报告生成接入双门槛评估：
  - `scripts/benchmark_to_markdown.py` 新增 `--absolute` 模式（`--absolute --small <json> [--large <json>] --baseline <mock.json> --output <md>`）：渲染日期命名绝对分报告——每维度三列对比（3-small / 3-large / mock 基线 + Δ）、双门槛结论（发布门槛逐维对比 + 通过门槛矛盾链/均分明细，复用 `evaluate_gates` 逐模型独立判定，两模型各自一行结论）、矛盾链维度说明、独立侧套件引用（`tests/quality/temporal/`）与 ADR-0001 引用；`--large` 缺失时该列以 — 呈现且仅评估 small 门槛；基线维度集合不一致时抛 `GateEvaluationError` 明确报错（不静默漏列），CLI 退出码 2。
  - `scripts/run_real_benchmarks.sh` 接线：跑分后自动生成 `docs/benchmarks/absolute-scores-<YYYY-MM-DD>.md`（日期命名、可多期共存、可回溯）；中间产物（双列对照、DeepSeek 报告，及 CI 的 mock-results.md）统一输出到 gitignored 的 `reports/`，不再污染 `docs/`；无 `OPENAI_API_KEY`（provider factory 回退，非真实 OpenAI 嵌入）时跳过绝对分报告并告警；结尾打印入库提醒（审阅 → git add → README 加链接）。
  - `docs/benchmarks/README.md`「已发布的报告」死链清理：移除从未生成的 `mock-results.md` / `real-llm-results.md` / `real-llm-deepseek-results.md` 三个链接，改链已入库的 `mock-baseline.json`，写明绝对分报告发布流程；真实嵌入跑分不进 CI，由维护者手动跑并提交入库。
  - 渲染层单元测试（`tests/benchmarks/test_benchmark_to_markdown.py` 新增 6 例）：三列对比 + 双门槛结论渲染 / 单模型门槛失败点名（含数字）/ large 缺失容错 / 基线缺维度报错 / CLI `--absolute` 写文件 / 基线不匹配退出码 2。

## [0.4.0] — 2026-07-03

> 合并 M1（部署加固、OTel、基准、CI 自动化）与 M2（API / SDK / 安全加固）全部工作项，发布 v0.4.0。M1 细节见 `git log --grep=feat\(m1\)`；M2 细节见 `git log --grep=feat\(m2\)`。本节仅列摘要。

### Security

- **P0: Cross-entity upload authorization** — `POST /v1/upload` now enforces entity authorization via `_authorize_entity(request, entity_id)` before any I/O. Previously, any authenticated key with `write` permission could upload files into any entity's namespace, breaking per-entity isolation. The check runs *before* the MinIO PUT, so a malicious request never produces a stored object.

### Added

- **P1.2a: `add()` override parameters** — `engine.add()`, the REST `/v1/memories` route, and the SDK `EmeraldClient.add()` now accept direct `memory_type`, `confidence`, and `valid_until` arguments. Precedence: explicit arg > `metadata` dict > chunker default. Lets an onboarding form that has just captured a structured preference skip the LLM classification step.
- **P1.2b: `pipeline_status` fact-extraction metadata** — `GET /v1/pipelines/{id}` now returns `fact_extraction_status` (`success` / `failed` / `skipped`) and `memory_count` so clients can render "extracted N facts" progress. Pipeline job model + Alembic migration `007_add_pipeline_fact_extraction_status` add the columns. Tasks write the column only in `index_task` (the previous duplicate write in `chunk_task` was dead code that index_task overwrote unconditionally).
- **P1.2c: SDK typed exceptions** — New `emerald.sdk.exceptions` module exposes `EmeraldAuthError` (401/403), `EmeraldNotFoundError` (404), `EmeraldValidationError` (422, carries `field_errors`), `EmeraldRateLimitError` (429, carries `retry_after`), `EmeraldServerError` (5xx), `EmeraldNetworkError` (connection/DNS failures). All inherit from `EmeraldError`. The old `httpx.HTTPStatusError` is no longer surfaced to callers.
- **P1.2d: SDK async context manager** — `EmeraldClient` now implements `__aenter__` / `__aexit__`. Use `async with EmeraldClient(...) as client:` and the underlying httpx connection is closed automatically.
- **P2.1: OAuth state in Redis with TTL** — `/v1/connectors/{provider}/connect` and `/callback` now persist OAuth state tokens in Redis (`emerald:oauth_state:{token}`) with a 10-minute TTL via the new `OAuthStateStore`. Replaces the in-process dict that broke multi-worker deployments. `consume()` uses Redis `GETDEL` for atomic read+delete; older redis-py clients fall back to non-atomic get+delete. TTL is configurable via `OAUTH_STATE_TTL_SECONDS` env var. When Redis is unavailable, the route fails with **503** (loud failure) rather than silently accepting tokens that won't work across workers.
- **P2.2: CORS production hardening** — `CORS_ALLOWED_ORIGINS` default is now empty (most restrictive). A bare `*` is **rejected at startup in production** via a Pydantic validator; the dev environment still allows `*` for local browser testing. Prevents the failure mode where a permissive CORS default leaks data via a stolen API key.
- **P3: OpenAPI auto-generation** — `docs/api/openapi.yaml` is now generated by `scripts/generate_openapi.py` from the running FastAPI app. The script is idempotent and supports `--check` mode for CI. A new `tests/api/test_openapi_drift.py` (5 tests) fails CI if the published spec drifts from the actual routes.

### Fixed

- **P1-1: 事件驱动摄入 entity_id 约定错配**（issue #6 验证遗留）— `handle_event` 与兜底同步任务 `sync_all_bindings_task` 把 binding 的内部 UUID（FK 到 `entities.id`）当作 `entity_id` 传入管线，而管线按 `external_id` 解析实体 → 每次事件驱动摄入都 `Entity not found`。修复：适配层经 `binding_store.get_entity_external_id` 将内部 UUID 解析为 external_id 后再入管线；binding 对应实体已删除时 fail-soft（记录错误，不崩溃）。同时修复 `get_binding_by_account`：同一 hub_account_id 跨实体重复绑定时不再抛 `MultipleResultsFound`，改为取首个并记 warning。
- **P1-2: `StackOneHubClient.list_accounts` 对裸 JSON list 响应崩溃**（issue #6 验证遗留）— 真实 API 返回 `[]`（非 `{"data": []}`），`resp.get("data", ...)` 在 list 上调用 → AttributeError，`/v1/sources/refresh` 500。修复：同时容忍 `[...]` 与 `{"data": [...]}`/`{"results": [...]}` 两种响应形状。
- **P1-3: `/v1/sources` 路由 stdlib logging 传 structlog kwargs**（issue #6 验证遗留）— `sources.py` 的 connect/refresh 错误路径用 stdlib logger 调用 `logger.warning(..., error=...)` → TypeError，502 错误路径实际以 500 崩溃。修复：改用 structlog logger。
- **OpenAPI path / endpoint gaps** — the published spec was missing 6 v1 endpoints (`POST /memories/{id}/validate`, `GET /profiles/{id}/memory.md`, `GET/PUT/DELETE /profiles/{id}/config`, `POST /sessions`, `GET /sessions/verify`, `POST /conflicts/{id}/resolve`). Auto-generation eliminates this class of bug permanently.
- **v2 routes removed** — v2 was a strict subset of v1 throughout v0.3.x; for v0.4.0 we drop the `/v2` prefix entirely. All improvements (error codes, pagination, rate-limit headers, OpenAPI auto-gen) land directly on `/v1/*`. `tests/api/test_v2_route_parity.py` is replaced by `tests/api/test_route_completeness.py`, which fails if any v1 route is missing or undocumented.
- **Chunked `fact_extraction_status` write removed** — `chunk_task` used to write `fact_extraction_status` to the DB; `index_task`'s `finally` block overwrote that value unconditionally, making the chunk write dead. The write is removed; `index_task` is now the single source of truth. `tests/pipeline/test_chunk_task_no_fact_status.py` pins the contract.
- **`chunk_count` field removed from `PipelineStatus`** — the field was declared in the schema and SDK but always returned `0` (the `pipeline_jobs` table doesn't track it), misleading clients. Removed from the Pydantic schema, the SDK dataclass, the route, and the docs.

### Changed (refactor)

- **N5: Centralised `_authorize_entity`** — five route modules (`memories`, `search`, `profiles`, `conflicts`, `upload`) all had a copy of the same 4-line helper. The helper now lives once in `emerald/api/dependencies.py` as `authorize_entity`; routes import and alias it as `_authorize_entity` for backward compatibility with the security test patches.
- **N1: Shared `engine` and `clean_settings` fixtures** — extracted from the 5+ test files that had built their own in-memory engine, plus a `clean_settings` fixture that strips env vars and forces pydantic-settings to use only model defaults. Both live in `tests/conftest.py`.
- **I2: SDK `upload()` reuses the shared httpx client** — previously each `upload()` call built a new `httpx.AsyncClient` (with a 120s timeout) just for one request. Now the shared client handles the call with a per-request `timeout=` override. Cuts the TLS handshake per upload.
- **I3: Flattened `_raise_for_status`** — the SDK's error-mapping helper was 30 lines of nested `isinstance` / `body.get()` calls; refactored to delegate to three small helpers (`_extract_error_message`, `_extract_retry_after`, `_extract_field_errors`).
- **I4: `datetime` import moved to top of `emerald/sdk/client.py`** — no more local import inside `add()`.
- **I5: `_resolve_override` helpers** — `engine._index` had three nested if-blocks to apply the explicit-arg > metadata > chunker precedence; now delegates to `_resolve_override()` and `_resolve_override_valid_until()` (the second parses ISO 8601 strings for `valid_until`).
- **N2: `OAuthStateStore` moved to `emerald/api/_state_store.py`** — the storage abstraction no longer lives in the connector route file, making it independently testable and reusable.

### Tests

- **657 tests pass, 1 skipped, 0 failures** (was 601 before this work). New files:
  - `tests/api/test_upload_authorization.py` (4 tests, including a new end-to-end test using the real `authorize_entity` helper)
  - `tests/api/test_openapi_drift.py` (5 tests)
  - `tests/api/test_v2_route_parity.py` (5 tests)
  - `tests/api/test_oauth_state_store.py` (15 tests, including a runtime 503 test that catches silent in-memory fallback regressions)
  - `tests/api/test_cors_validation.py` (6 tests)
  - `tests/pipeline/test_chunk_task_no_fact_status.py` (2 tests)
  - `tests/sdk/test_add_overrides.py` (7 tests, including 2 precedence tests)
  - `tests/sdk/test_exceptions_and_context.py` (15 tests)
  - `tests/sdk/test_pipeline_status_fields.py` (5 tests)

### Migration notes

- **Alembic migration `007_add_pipeline_fact_extraction_status`** — adds `pipeline_jobs.fact_extraction_status` (String(20), nullable) and `pipeline_jobs.memory_count` (Integer, default 0). Run `alembic upgrade head` before deploying.
- **`CORS_ALLOWED_ORIGINS=*` rejected in production** — existing prod deployments using a wildcard must set an explicit list before upgrading. The new validator fails the startup if `EMERALD_ENV=production` and the wildcard is present.
- **SDK exception types** — existing callers catching `httpx.HTTPStatusError` must catch `EmeraldError` (or a specific subclass) instead. The broad base catches everything.
- **OAuth state tokens** — no client action required; the in-memory dict is gone. Existing in-flight OAuth flows at the moment of upgrade will see their state tokens discarded (they'll need to restart the flow).
- **v2 API removed** — clients pointing at `/v2/*` must switch to the corresponding `/v1/*` path. The v1 path was always a strict superset, so the only change is dropping the `v2` prefix from URLs. The published `docs/api/openapi.yaml` is now single-version.

### Earlier in this release (2026-06-02 to 2026-06-22)

> 这批 M3 图谱智能增强 + 基准升级 + 生产基础设施工作在 v0.3.0 之后、M2 之前完成，与上面 M1 / M2 同属于 v0.4.0 的内容。

### Added

#### M3 — Graph Intelligence 补齐
- **LLM 事实提取** (`emerald/pipeline/chunking/fact_extractor.py`)：DeepSeek V4-Flash 驱动的多事实分解、类型分类（fact/preference/episodic）、置信度评分、summary 生成
- **图谱搜索遍历** (`emerald/core/search.py:_expand_relationships`)：沿 EXTENDS / DERIVES_FROM 关系双向深度=1 遍历，`expansion_factor=0.85`
- **首选项强化** (`emerald/core/engine.py:_strengthen_preferences`)：重复偏好 +0.05 置信度（上限 0.95）
- **关系推断 LLM 化** (`emerald/core/relationship.py`)：DeepSeek 优先，OpenAI 降级
- **语义去重** (`emerald/core/engine.py:_check_duplicate`)：bigram 快速过滤 + LLM 边界判定
- **Cross-encoder 重排序升级** (`emerald/core/search.py`)：三级降级链（cached cross-encoder → embedding cosine → keyword boost），模型实例级缓存，支持 sentence-transformers 热加载
- **关系推断 LLM-first** (`emerald/core/relationship.py`)：LLM 优先分类 + 规则降级；新增 bigram 快速预滤跳过无关配对，避免浪费 LLM 调用
- **Profile config 端点** (`emerald/api/routes/v1/profiles.py`)：PUT/GET/DELETE `/v1/profiles/{entity_id}/config`，per-entity 画像配置覆写（Redis 持久化），ProfileManager 在 compute/merge 时旁加载
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
- `docs/superpowers/plans/2026-06-21-m1-v0.4.0-implementation.md`：M1 (v0.4.0) 实施计划（2228 行，TDD bite-sized 任务）— M1 完成后已归档为 `ARCHIVED-2026-06-21-m1-v0.4.0-implementation.md`
- 删除本地 `_references/supermemory-main` 仓库引用
- **2026-06-22：** 所有文档同步更新，生产就绪评估反映最新状态；过时 superpowers plans/specs 归档（10 份）

#### 2026-06-22 补齐（最后 3 项 Stub 清零）
- **Cross-encoder 重排序升级**：三级降级链（cached CE → embedding cosine → keyword boost）
- **关系推断 LLM-first**：LLM 优先 + bigram 预滤 + 规则降级
- **Profile config 端点**：PUT/GET/DELETE `/v1/profiles/{entity_id}/config`，per-entity 配置覆写（Redis 持久化）

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
- v0.3.0 → v0.4.0 测试数：484 → **657**（+173，+36%）
- 重点新增：
  - `tests/pipeline/test_fact_extractor.py`（11 tests，DeepSeekFactExtractor）
  - `tests/pipeline/test_semantic_text_chunker.py`（6 tests）
  - `tests/pipeline/test_conversation_chunker.py`（+49 tests）
  - `tests/unit/test_lock.py`（Redis 锁）
  - `tests/unit/test_reconciliation.py`（双写一致性）
  - `tests/unit/test_embedder.py`（fastembed）
  - `tests/core/test_search.py`（+193 行图谱遍历测试；+5 重排序测试）
  - `tests/core/test_profile_manager.py`（+8 测试：profile config CRUD + 效果验证）
  - M2 新增 9 个测试文件 / 56 测试（typed 异常、OpenAPI drift、OAuth state、CORS 校验、SDK override、chunk_task 守卫、v2 route parity → route completeness）
- 5 个测试失败 → 全部修复

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
