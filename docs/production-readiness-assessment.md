# Emerald 生产级可用性评估报告

> **更新日期：2026-08-11**（基于 v0.6.0 release——v0.5.0 完成 M2 质量套件 / 绝对分报告 / 安全审计，v0.6.0 退役自研连接器）
>
> **总体结论：Emerald 已具备受控环境生产部署的基础条件。** M1（Dockerfile/K8s/OTEL/基准/CI）完成；M2（v0.5.0，按 ADR-0001 重裁剪为「测试卫生 → 独立侧质量套件 → 真实嵌入绝对分报告 → 安全审计」）全部交付；v0.6.0 按 ADR-0004 退役自研连接器（连接能力外包给连接中心 Totem）。剩余差距：NER/多跳推理（M3）、负载压测验证（D2-D3）、框架集成生态（仅 Pandaria）。
>
> **可部署性评级：🟢 生产化进行中（推进至 ~80%）。** 建议路径：M3 生态爆发（NER / 多跳 / LangChain.js 等）→ M4 智能深度（高级遗忘 / 负载压测）→ v0.9.0 Production-Ready Beta。

---

## 评估方法

本评估从 10 个维度检查 Emerald 的生产就绪度：

1. 架构与部署
2. 数据持久化与迁移
3. 认证与授权
4. 可观测性
5. 性能与扩展性
6. 容错与恢复
7. 安全
8. 测试覆盖
9. 功能完整性
10. 运维与文档

每个维度按 🟢（生产就绪）、🟡（基本可用但有风险）、🔴（不满足生产要求）评级。

---

## 1. 架构与部署

| 检查项 | 状态 | 说明 |
|---|---|---|
| Docker Compose 开发环境 | 🟢 | 8 个服务完整：API、Worker、Beat、PostgreSQL、Neo4j、Redis、MinIO、Nginx + MCP Server，健康检查齐全 |
| K8s 生产部署 | 🟢 | Deployment（API/Worker/Beat）、HPA（CPU 70%/Memory 80%）、Ingress（50MB body limit）、Service、CronJob 备份、ConfigMap、Secret、Namespace 全部就绪 |
| Dockerfile 多阶段构建 | 🟢 | production stage 独立 `pip install`，`.dockerignore` 排除非必要文件，`requirements-prod.txt` 仅含运行时依赖，镜像体积 <1.2GB |
| 服务依赖管理 | 🟢 | `lifespan` 中按序初始化 Neo4j → Redis → PostgreSQL，关闭时反向释放 |
| 进程模型 | 🟢 | Uvicorn ASGI + Celery 异步任务队列，符合 Python 高并发最佳实践 |

---

## 2. 数据持久化与迁移

| 检查项 | 状态 | 说明 |
|---|---|---|
| 数据库迁移（Alembic） | 🟢 | 5 个 migration：初始 schema → pgvector embedding → pipeline_jobs content_type → sync_metadata → `009_drop_connectors`（v0.6.0 退役连接器表，数据绑定由 `source_bindings` 承接） |
| pgvector HNSW 索引 | 🟢 | `m=16, ef=construction=64`，向量列类型 `vector(1536)`，O(log n) 近似搜索 |
| 数据库连接池 | 🟢 | SQLAlchemy `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True` |
| Neo4j 连接管理 | 🟢 | `max_connection_pool_size=50`, `connection_acquisition_timeout=30`, `max_transaction_retry_time=30`（v0.4.0 已配置） |
| Redis 连接 | 🟢 | `decode_responses=True`，有 `aclose()` 降级处理 |
| 数据一致性 | 🟢 | `ReconciliationEngine` 后台扫描孤立节点并补偿（双写不一致已修复） |
| 备份策略 | 🟢 | K8s CronJob 每日 2AM 自动 `pg_dump` |

---

## 3. 认证与授权

| 检查项 | 状态 | 说明 |
|---|---|---|
| API Key 认证 | 🟢 | Bearer Token 格式，`em_` 前缀校验，SHA-256 哈希存储（不存明文） |
| API Key 过期 | 🟢 | 支持 `expires_at` 字段，过期返回 401 |
| API Key 管理 | 🟢 | v0.5.0：`POST/GET/DELETE /v1/keys`（admin 权限 + 实体作用域），生产 onboarding 路径就绪 |
| 权限控制 | 🟢 | `read`/`write`/`admin` 三级权限，写操作单独校验 |
| 速率限制 | 🟢 | Redis 滑动窗口，按端点配置（memories 60/min、search 120/min、profiles 300/min、upload 10/min），返回 429 + Retry-After |
| Redis 不可用时限流 | 🟡 | 优雅降级——Redis 不可用时跳过限流，不阻塞请求（fail-open；安全审计列为观察项） |
| CORS | 🟢 | 环境变量 `CORS_ALLOWED_ORIGINS` 区分 wildcard/严格模式；检测到 `*` 记录 warning |

---

## 4. 可观测性

| 检查项 | 状态 | 说明 |
|---|---|---|
| 结构化日志 | 🟢 | structlog JSON 格式，全链路 `request_id`，每个管线阶段记录 entity_id/内容类型/耗时/分块数/关系数/错误状态 |
| 健康检查 | 🟢 | `/v1/health` 探测 PostgreSQL、Neo4j、Redis、MinIO，返回 `ok`/`degraded` + 各组件状态 |
| Prometheus 指标 | 🟢 | `/v1/metrics` 暴露 FastAPI 自动指标 + 业务指标（search_latency、pipeline_jobs_total 等） |
| 分布式追踪 | 🟢 | OTEL auto-instrumentation（FastAPI/httpx/asyncpg/redis/celery）+ 手动 span + trace_id 注入 structlog + collector 部署文档；Neo4j 无 PyPI instrumentation 包，使用手动 span |
| 告警机制 | 🟡 | `docs/deployment/observability.md` 含告警规则建议，需外部 Prometheus Alertmanager 落地 |

---

## 5. 性能与扩展性

| 检查项 | 状态 | 说明 |
|---|---|---|
| 异步架构 | 🟢 | FastAPI + asyncpg + neo4j async driver + aioredis |
| 水平扩展（API） | 🟢 | K8s HPA 2-10 replicas，基于 CPU/Memory |
| 水平扩展（Worker） | 🟡 | Celery Worker 可扩展，但 Beat 为单点（replicas=1） |
| 嵌入缓存 | 🟢 | Redis 7 天缓存，mget/pipeline 批量获取；缓存键纳入模型标识（v0.5.0 修复 mock/真实污染） |
| 画像缓存 | 🟢 | Redis 24h TTL，摄入时主动失效 |
| 向量搜索 | 🟢 | HNSW 索引，O(log n) |
| 重排序 | 🟢 | **三级降级链**：cached cross-encoder（sentence-transformers）→ embedding cosine → keyword boost；模型级缓存，首次加载后复用 |
| 查询改写 | 🟢 | LLM 化（DeepSeek → OpenAI 降级）+ 模式匹配降级 |
| 本地嵌入模型 | 🟢 | `FastEmbedProvider`（ONNX runtime，无 PyTorch），完全离线可用 |
| 画像计算 | 🟡 | 冷缓存时从 Neo4j 拉取 200 条记忆计算，高实体数时可能成为瓶颈 |
| **性能 SLA 验证** | 🔴 | 未做（画像 <100ms、搜索 P50/P99）。v0.5.0 决议整体延后，集中功能不集中性能；移至 M4（D2-D3） |

**性能预期（估算，未压测验证）：**
- 画像获取（缓存命中）：< 10ms
- 画像获取（缓存未命中）：Neo4j 查询 200 条 + 排序筛选，~50-200ms
- 搜索（向量）：HNSW + 过滤，~20-50ms
- 搜索（keyword fallback）：全量拉取 100 条 + 遍历，O(n)，随记忆数增长

---

## 6. 容错与恢复

| 检查项 | 状态 | 说明 |
|---|---|---|
| 异常体系 | 🟢 | 完整的异常层次：PipelineError、ExtractionError、ChunkingError、EmbeddingError、IndexingError、AuthenticationError 等（连接器异常类已随 v0.6.0 退役移除） |
| 嵌入 API 重试 | 🟢 | tenacity 指数退避（max 3 次，1-10s 等待），区分 retryable（429/502/503/504）和非 retryable（401/400） |
| Celery 任务重试 | 🟢 | extract_task max_retries=3，chunk_task/embed_task max_retries=2，指数退避 |
| 提取器缺失降级 | 🟢 | 启动时 `try/except ImportError`，缺失的提取器记录 warning，服务继续启动 |
| 嵌入失败降级 | 🟢 | embedder=None 时回退 keyword search |
| Redis 失败降级 | 🟢 | Redis 不可用时跳过缓存/限流 |
| 双写一致性补偿 | 🟢 | `ReconciliationEngine` 后台扫描孤立节点，补偿标记 `is_latest=False` + `replaced_by="reconciliation_failed"` |
| 分布式锁 | 🟢 | `beat_lock` Redis 分布式锁，防 Celery Beat 多实例重复执行 |
| 管线断点续传 | 🟡 | PipelineJob 有 status/retry_count，但无明确的失败自动恢复机制 |
| graceful shutdown | 🟡 | lifespan 有关闭逻辑，但未处理正在执行的请求/任务 |

---

## 7. 安全

| 检查项 | 状态 | 说明 |
|---|---|---|
| API Key 存储 | 🟢 | 仅存储 SHA-256 哈希，不存明文 |
| 传输加密 | 🟡 | 文档说"生产环境 HTTPS"，但代码中无强制 HTTPS 重定向 |
| 实体隔离 | 🟢 | 所有操作限定 `entity_id`，记忆/向量/文件按实体隔离 |
| 文件大小限制 | 🟢 | upload 50MB 限制 |
| 输入校验 | 🟢 | Pydantic 模型校验，FastAPI 自动处理 |
| SQL 注入防护 | 🟢 | SQLAlchemy 参数化查询 |
| SSRF 面修复 | 🟢 | v0.5.0 安全审计修复：`POST /v1/extract-url` 挂载 `api_key_auth` + `rate_limit`，关闭未认证出站 fetch |
| 依赖安全扫描 | 🟢 | `.github/workflows/security.yml` — pip-audit（每周+PR，**0 漏洞硬门禁**）、Gitleaks（push + **全历史**扫描，8.30.1 固定版本）、CodeQL 静态分析；`.gitleaks.toml` 含项目定制规则 |
| PII 日志脱敏 | 🟢 | `emerald/core/sanitizer.py` — structlog processor，生产环境自动启用；覆盖 email/电话/APIkey/IP/信用卡/SSN/JWT + 敏感字段名脱敏 |
| 安全策略文档 | 🟢 | `SECURITY.md` — 支持版本、漏洞报告流程、信任边界图、12 项安全措施清单 |

> **v0.5.0 安全审计（M2 #14）完成 — 0 个 P0/P1 漏洞**，报告落 `docs/verification/security-audit-2026-08.md`：pip-audit 双模式 0 已知漏洞并升级硬门禁；Gitleaks 全历史（237 commits）零真实泄漏（31 个命中全为 dev 占位凭据）；修复 3 个配置缺陷（跨行误报 / allowlist 结构失效 / 全历史从未被 CI 覆盖）；API 层清单五项 4 项达标、`/v1/extract-url` SSRF 面修复。观察项 5 条记录于报告 §5，不阻塞。

> **v0.6.0 连接器退役的净安全收益**：删除了 OAuth 凭证加密路径（AES-256-GCM via `cryptography`）与 GitHub webhook 接收面——两者随 `emerald/connectors/` 一并移除，凭证管理与 OAuth 授权外包给连接中心（Totem），Emerald 攻击面相应收窄；依赖 `cryptography` 一并移除。

---

## 8. 测试覆盖

| 检查项 | 状态 | 说明 |
|---|---|---|
| 测试函数数量 | 🟢 | **838 个测试函数**通过（v0.5.0：质量套件 +18 / 安全 +10 / 基准链路新增），覆盖核心引擎、搜索、画像、认证、限流、异常、边缘情况 |
| 测试类型 | 🟢 | 单元测试、集成测试（Docker Compose）、负向测试、边缘情况、并发测试、质量套件（时序/遗忘/图谱精度）、基准链路 |
| 连接器测试 | ✅ 已退役 | 自研连接器 E2E/集成测试已随 v0.6.0 旧代码删除（issue #7，ADR-0004）；连接中心路径由 Totem Pilot 验证（`docs/verification/totem-pilot-verification.md`） |
| 独立侧质量套件 | 🟢 | v0.5.0：`tests/quality/temporal/` 三 section + CI 聚合门（`quality-temporal`）；时序正确性 65 例 / 遗忘有效性 / 图谱关系精度 61 例，确定性语料 + mock 嵌入 + 规则路径 + 真实存储（docker-compose.test.yml） |
| 端到端测试 | 🟢 | `docker-compose.test.yml` + `.env.test` |
| 覆盖率配置 | 🟢 | `.coveragerc` omit 配置 |
| 基准测试 | 🟢 | v0.5.0：首个真实嵌入绝对分报告公开（`docs/benchmarks/absolute-scores-2026-08-11.md`，7/7 维度通过，Aggregate 0.943） |

---

## 9. 功能完整性

| 功能模块 | 状态 | 说明 |
|---|---|---|
| **记忆引擎** | 🟢 | 提取 → 分块 → 嵌入 → 索引完整链路 |
| **关系推断** | 🟢 | **LLM-first**（DeepSeek → OpenAI 降级）+ 规则降级；bigram 快速预滤跳过无关配对。v0.5.0 修复规则矛盾检测误伤（含「不」即判取代曾致 19 条无关事实被标记过期；Fact Recall 0.133→0.933） |
| **用户画像** | 🟢 | 静态 + 动态双层，Redis 缓存，主动失效 |
| **混合搜索** | 🟢 | hybrid/memory/rag 三种模式，结果合并去重 |
| **自动遗忘** | 🟢 | ForgetEngine 走 `list_entity_ids()` 公共接口；三策略（时间过期 / 噪音过滤 / 情节衰减） |
| **内容提取** | 🟢 | 7 种提取器（text/url/pdf/image/audio/video/code）；v0.5.0 修复 `text/markdown` 经 MIME 路径摄入（#4） |
| **分块** | 🟢 | 7 种分块器（text/conversation/markdown/pdf/code + v0.5.0 新增 json/csv 自动检测） |
| **连接器 / 数据源** | 🟢 已退役 | 自研连接器（github/gmail/google_drive/notion OAuth + webhook + Celery 同步）已于 v0.6.0 按 ADR-0004 全部删除；连接能力外包给连接中心 Totem（内部自托管动作层，v1 upstream = Feishu Docs，可替换）。Emerald 侧保留 `ConnectionHub` 抽象 + `TotemHubClient` + `/v1/sources/*` 绑定路由 + 事件驱动摄入；Pilot 验证通过（2026-08-10） |
| **MCP Server** | 🟢 | stdio + SSE 双模式，3 个工具 |
| **Python SDK** | 🟢 | async client，4 核心方法 + 辅助方法 |
| **TypeScript SDK** | 🟢 | v0.5.0：`sdk/typescript/`，对齐 Python SDK 方法集 |
| **文档列表** | 🟢 | `GET /v1/files` Document 分页查询（游标分页 `page_token` + `page_size`） |
| **幂等写入** | 🟡 | Redis `idempotency_key` (1h TTL) 已实现；`customId` 仍在路线图（v0.7+ 计划） |
| **metadata 过滤** | 🟢 | MongoDB 风格 `$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne` 完整支持 |

---

## 10. 运维与文档

| 检查项 | 状态 | 说明 |
|---|---|---|
| README | 🟢 | 完整，含功能概览、API 示例、部署步骤 |
| AGENTS.md | 🟢 | 架构原则、设计决策、开发指南，不可协商约束清晰；含「功能三问」立项 gate |
| 架构文档 | 🟢 | 系统概览、数据模型、管线、API 设计、连接器（已收敛为连接中心）、部署方案 |
| ADR | 🟢 | 4 份：0001 度量体系 / 0002 Spaces / 0003 Web UI 产品层 / 0004 连接器外包 |
| 集成指南 | 🟢 | SDK 用法、REST API、MCP 配置 |
| API 文档 | 🟢 | OpenAPI 自动生成 + 入库（`docs/api/openapi.yaml`，漂移测试守卫）+ 错误码 + 双模型报告 |
| 变更日志 | 🟢 | `CHANGELOG.md` 完整，v0.5.0 / v0.6.0 段详尽 |
| 版本策略 | 🟢 | v1 API 为统一版本；所有改进（错误码、分页、限流头）在 v1 中直接提供 |
| 社区/支持 | 🔴 | 无 Discord/论坛/Slack，issue 响应机制未建立 |

---

## 关键问题清单（按优先级排序）

> 反映 v0.6.0 发布后的实际状态。✅ 表示已修复，⏳ 表示路线图中计划中。

### 🔴 P0 — 生产阻塞问题

| # | 原问题 | 状态 | 说明 |
|---|---|---|---|
| 1 | **双写不一致（Neo4j + pgvector）** | ✅ 已修复 | `ReconciliationEngine` 后台补偿孤立节点 |
| 2 | **CORS `allow_origins=["*"]`** | ✅ 已修复 | 环境变量区分 dev/wildcard/prod 模式 |
| 3 | **MinIO 同步调用阻塞事件循环** | ✅ 已修复 | `asyncio.to_thread` 包裹 |
| 4 | **本地嵌入模型未实现** | ✅ 已修复 | `FastEmbedProvider` (ONNX runtime) |
| 5 | **性能 SLA 未验证** | 🔴 延后 | 画像 <100ms / 搜索 P50/P99 未压测；v0.5.0 决议整体延后至 M4（D2-D3）。**当前唯一未解决的 P0** |

### 🟡 P1 — 高风险问题

| # | 原问题 | 状态 | 说明 |
|---|---|---|---|
| 6 | **关系推断引擎过于初级** | ✅ 已修复 | LLM-first + 规则降级 + bigram 预滤；v0.5.0 修复矛盾检测误伤 |
| 7 | **重排序 Stub** | ✅ 已修复 | 三级降级链：cached cross-encoder → embedding cosine → keyword boost |
| 8 | **遗忘引擎 Neo4j 实现不完整** | ✅ 已修复 | `list_entity_ids()` 公共接口 |
| 9 | **Neo4j 驱动无连接池配置** | ✅ 已修复 | 生产级参数已配置 |
| 10 | **无幂等写入** | 🟡 部分修复 | Redis `idempotency_key`；`customId` 待 v0.7+ |
| 11 | **`/v1/files` stub 实现** | ✅ 已修复 | 完整 Document 游标分页查询 |
| 12 | **无分布式锁** | ✅ 已修复 | `beat_lock` Redis 分布式锁 |
| 13 | **安全审计未做** | ✅ 已修复 | v0.5.0 完成（0 P0/P1），门禁硬化 |

### 🟢 P2 — 优化建议

| # | 原问题 | 状态 | 说明 |
|---|---|---|---|
| 14 | **缺少自定义业务指标** | ✅ 已修复 | `prometheus-fastapi-instrumentator` + 业务指标 |
| 15 | **Dockerfile 非最优** | ✅ 已修复 | production stage 独立 pip install |
| 16 | **画像冷缓存计算瓶颈** | 🟡 部分修复 | 多因子评分；冷缓存仍全量重算，增量更新是 M3+ 计划 |
| 17 | **keyword search 性能** | ⏳ 未处理 | 如 Staging 负载测试显示瓶颈则在 M4 处理 |
| 18 | **版本演进策略** | ✅ 已修复 | API 版本统一为 v1 |

**17 项已识别问题中：**
- ✅ 已修复：14 项（82%）
- 🟡 部分修复：2 项（幂等 customId、画像冷缓存）
- 🔴 延后：1 项（性能 SLA 验证 — P0，移至 M4）
- ⏳ 待评估：1 项（keyword search 性能，依赖压测数据）

---

## 生产部署建议

### 场景 A：内部试运行（推荐当前阶段）

✅ **可以部署**，需满足以下条件：
- 限制为内部用户/低流量场景（< 1000 DAU）
- 配置独立 Staging 环境，运行负载测试
- 可选启用本地嵌入（fastembed）或 OpenAI/SiliconFlow 网关嵌入
- 设置监控告警（Prometheus + Grafana + Alertmanager）
- 制定数据备份和灾难恢复流程
- 启用 ReconciliationEngine 后台任务（每 30 分钟）修复孤立节点
- 接受 API 仍可能演进（能力构建期，v0.6.0 不保证兼容）

### 场景 B：生产环境（面向外部用户）

⚠️ **不建议立即部署**，需完成路线图 M3-M5：
- M3（v0.7.0）：NER / 多跳推理 / LangChain.js / Vercel AI / Mastra / 文档 overhaul
- M4（v0.8.0）：高级遗忘 / 实时记忆整合 / 负载压测基础设施 + 2 周 Staging 压测（解决 P0 性能 SLA）
- M5（v0.9.0）：72h soak test / 模糊测试 / 部署文档 / 运维手册 → Production-Ready Beta
- 路线图 [`docs/roadmap.md`](roadmap.md) §10 详述 v1.0 提升的 7 个硬性条件

---

## 与 Supermemory 的生产级差距

| 维度 | Emerald v0.6.0 | Supermemory | 差距状态 |
|---|---|---|---|
| **基准验证** | ✅ 真实嵌入绝对分报告公开（7/7 维度，Aggregate 0.943）+ 独立侧质量套件全绿 | ✅ 自称三项基准最优 | 度量体系独立（ADR-0001），不可直接比较 |
| **负载验证** | ❌ 未验证 | ✅ 10k 文档/小时 | M4 计划（P0 性能 SLA） |
| **重排序** | ✅ 三级降级链 | ✅ cross-encoder | 已完成 |
| **查询改写** | ✅ LLM 化 | ✅ LLM-based | 已对齐 |
| **关系推断** | ✅ LLM-first + bigram 预滤 + 规则降级 | ✅ 更成熟的语义分析 | 已完成 |
| **metadata 过滤** | ✅ MongoDB 风格 | ✅ 同等 | 已对齐 |
| **分布式部署** | ✅ K8s 模板完整 | ✅ 全球分布式 | 架构对齐 |
| **SLA 保障** | ❌ 未定义 | ✅ SaaS SLA | M5 路线 |
| **版本演进** | 🟢 v1 统一版本 | ✅ v3→v4 演进 | 已完成 |
| **消费者产品** | ❌ 无（Web UI 是产品层 ADR-0003，在范围内但未实现） | ✅ App + 插件 | 定位选择 |
| **连接器/集成** | 🟢 外包给连接中心 Totem（ADR-0004） | ✅ 原生多源 | 架构选择 |

**差距本质**：Emerald 的「骨架」+「核心能力」已对齐 Supermemory，度量体系独立且证据公开（绝对分报告 + 质量套件）。剩余差距集中在「生态成熟度」（真实生产负载验证、框架集成仅 Pandaria）和「产品形态」（无消费者产品，是定位选择）。详见 [`docs/comparison-supermemory.md`](comparison-supermemory.md) v2。

---

## 总结

| 维度 | 评级 | 核心说明 |
|---|---|---|
| 架构与部署 | 🟢 | 骨架完整，K8s 模板就位 |
| 数据持久化 | 🟢 | ReconciliationEngine 补齐双写一致性；连接器表已随 v0.6.0 迁移移除 |
| 认证与授权 | 🟢 | CORS 生产化，API Key 哈希存储，v0.5.0 Key 管理端点 |
| 可观测性 | 🟢 | Prometheus + 结构化 JSON + OpenTelemetry + 日志 trace_id 关联 |
| 性能与扩展性 | 🟡 | 能力已 LLM 化 / 三级降级；**性能 SLA 未压测验证（P0，延后 M4）** |
| 容错与恢复 | 🟢 | Reconciliation + 分布式锁 + 优雅降级 |
| 安全 | 🟢 | v0.5.0 安全审计 0 P0/P1，门禁硬化；v0.6.0 收窄攻击面（移除 OAuth/webhook） |
| 测试覆盖 | 🟢 | **838 测试函数** + 独立侧质量套件三节全绿 + 真实嵌入绝对分报告 |
| 功能完整性 | 🟢 | 核心能力对齐；连接器已退役为连接中心架构（ADR-0004） |
| 运维与文档 | 🟢 | 文档完整对齐；4 份 ADR；OpenAPI 漂移守卫 |

**综合评级：🟢 生产化进行中（~80%）**——M1 + M2（v0.5.0）+ 连接器退役（v0.6.0）已交付质量套件、绝对分报告、安全审计三项可信度证据。**唯一未解决 P0 是性能 SLA 验证**（延后 M4）。建议路径：**完成 M3-M5 后升级为 v0.9.0 Production-Ready Beta**（详见 [`docs/roadmap.md` §10](roadmap.md)）。

---

*评估时间：2026-08-11*
*评估版本：Emerald v0.6.0*
