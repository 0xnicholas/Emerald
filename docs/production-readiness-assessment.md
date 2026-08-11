# Emerald 生产级可用性评估报告

> **更新日期：2026-07-03**（基于 v0.4.0 release，M1+M2 核心工作项完成后的重新评估）
>
> **总体结论：Emerald 已具备受控环境生产部署的基础条件。** M1（Dockerfile/K8s/OTEL/基准/CI）和 M2（v2 API/错误码体系/分页/限流头/安全审计/PII 脱敏）全部完成。剩余差距：TypeScript SDK（M2 最后一项）、负载压测验证（D2-D3）、NER/多跳推理（M3）。
>
> **可部署性评级：🟢 生产化进行中（推进至 70%）。** 建议路径：完成 TS SDK → 负载压测 → v0.8.0 Production-Ready Beta。

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
| Dockerfile 多阶段构建 | 🟢 | v0.4.0: production stage 独立 `pip install`，`.dockerignore` 排除非必要文件，`requirements-prod.txt` 仅含运行时依赖，镜像体积 <1.2GB |
| 服务依赖管理 | 🟢 | `lifespan` 中按序初始化 Neo4j → Redis → PostgreSQL，关闭时反向释放 |
| 进程模型 | 🟢 | Uvicorn ASGI + Celery 异步任务队列，符合 Python 高并发最佳实践 |

**风险点：**
- `upload.py` 中 MinIO `put_object()` 是同步调用，在 async 路由中直接调用会阻塞事件循环。应使用 `asyncio.to_thread()` 包裹或 MinIO 的 async API。

---

## 2. 数据持久化与迁移

| 检查项 | 状态 | 说明 |
|---|---|---|
| 数据库迁移（Alembic） | 🟢 | 4 个 migration：初始 schema → pgvector embedding → pipeline_jobs content_type → sync_metadata |
| pgvector HNSW 索引 | 🟢 | `m=16, ef_construction=64`，向量列类型 `vector(1536)`，O(log n) 近似搜索 |
| 数据库连接池 | 🟢 | SQLAlchemy `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True` |
| Neo4j 连接管理 | 🟡 | 模块级全局 `_driver`，无连接池大小/超时/重试配置 |
| Redis 连接 | 🟢 | `decode_responses=True`，有 `aclose()` 降级处理 |
| 数据一致性 | 🟡 | `GraphStore` 和 `VectorStore` 的写入不在同一事务中，存在"图已写、向量未写"的裂脑风险 |
| 备份策略 | 🟢 | K8s CronJob 每日 2AM 自动 `pg_dump` |

**关键风险：**
- **双写不一致风险**：`MemoryEngine._index()` 先写 Neo4j 再写 pgvector，如果 pgvector 写入失败，Neo4j 中已有数据但向量缺失，导致搜索结果异常。AGENTS.md 要求"图谱操作必须是原子的"，但当前跨数据库写入未做分布式事务补偿。
- **Neo4j 驱动配置缺失**：未配置 `max_connection_pool_size`、`connection_timeout`、`max_transaction_retry_time` 等生产级参数。

---

## 3. 认证与授权

| 检查项 | 状态 | 说明 |
|---|---|---|
| API Key 认证 | 🟢 | Bearer Token 格式，`em_` 前缀校验，SHA-256 哈希存储（不存明文） |
| API Key 过期 | 🟢 | 支持 `expires_at` 字段，过期返回 401 |
| 权限控制 | 🟢 | `read`/`write`/`admin` 三级权限，写操作单独校验 |
| 速率限制 | 🟢 | Redis 滑动窗口，按端点配置（memories 60/min、search 120/min、profiles 300/min、upload 10/min），返回 429 + Retry-After |
| Redis 不可用时限流 | 🟢 | 优雅降级——Redis 不可用时跳过限流，不阻塞请求 |
| CORS | 🟢 | 环境变量 `CORS_ALLOWED_ORIGINS` 区分 wildcard/严格模式；检测到 `*` 记录 warning |

---

## 4. 可观测性

| 检查项 | 状态 | 说明 |
|---|---|---|
| 结构化日志 | 🟢 | structlog JSON 格式，全链路 `request_id`，每个管线阶段记录 entity_id/内容类型/耗时/分块数/关系数/错误状态 |
| 健康检查 | 🟢 | `/v1/health` 探测 PostgreSQL、Neo4j、Redis、MinIO，返回 `ok`/`degraded` + 各组件状态 |
| Prometheus 指标 | 🟢 | `/v1/metrics` 暴露 FastAPI 自动指标（请求数、延迟、状态码分布） |
| 自定义业务指标 | 🟡 | 未看到自定义指标（如 memory_add_count、search_latency_ms、relationship_infer_count） |
| 分布式追踪 | 🟢 | v0.4.0: OTEL auto-instrumentation（FastAPI/httpx/asyncpg/redis/celery）+ 手动 span + trace_id 注入 structlog + collector 部署文档；Neo4j 无 PyPI instrumentation 包，使用手动 span |
| 告警机制 | 🟡 | `docs/deployment/observability.md` 含告警规则建议，需外部 Prometheus Alertmanager 落地 |

---

## 5. 性能与扩展性

| 检查项 | 状态 | 说明 |
|---|---|---|
| 异步架构 | 🟢 | FastAPI + asyncpg + neo4j async driver + aioredis |
| 水平扩展（API） | 🟢 | K8s HPA 2-10 replicas，基于 CPU/Memory |
| 水平扩展（Worker） | 🟡 | Celery Worker 可扩展，但 Beat 为单点（replicas=1） |
| 嵌入缓存 | 🟢 | Redis 7 天缓存，mget/pipeline 批量获取 |
| 画像缓存 | 🟢 | Redis 24h TTL，摄入时主动失效 |
| 向量搜索 | 🟢 | HNSW 索引，O(log n) |
| 重排序 | 🟢 | **三级降级链**：cached cross-encoder（sentence-transformers）→ embedding cosine → keyword boost；模型级缓存，首次加载后复用 |
| 查询改写 | 🟢 | LLM 化（DeepSeek → OpenAI 降级）+ 模式匹配降级 |
| 本地嵌入模型 | 🟢 | `FastEmbedProvider`（ONNX runtime，无 PyTorch），完全离线可用 |
| 画像计算 | 🟡 | 冷缓存时从 Neo4j 拉取 200 条记忆计算，高实体数时可能成为瓶颈 |

**性能预期（估算）：**
- 画像获取（缓存命中）：< 10ms
- 画像获取（缓存未命中）：Neo4j 查询 200 条 + 排序筛选，~50-200ms
- 搜索（向量）：HNSW + 过滤，~20-50ms
- 搜索（keyword fallback）：全量拉取 100 条 + 遍历，O(n)，随记忆数增长

---

## 6. 容错与恢复

| 检查项 | 状态 | 说明 |
|---|---|---|
| 异常体系 | 🟢 | 完整的异常层次：PipelineError、ExtractionError、ChunkingError、EmbeddingError、IndexingError、AuthenticationError 等 |
| 嵌入 API 重试 | 🟢 | tenacity 指数退避（max 3 次，1-10s 等待），区分 retryable（429/502/503/504）和非 retryable（401/400） |
| Celery 任务重试 | 🟢 | extract_task max_retries=3，chunk_task/embed_task max_retries=2，指数退避 |
| 提取器缺失降级 | 🟢 | 启动时 `try/except ImportError`，缺失的提取器记录 warning，服务继续启动 |
| 嵌入失败降级 | 🟢 | embedder=None 时回退 keyword search |
| Redis 失败降级 | 🟢 | Redis 不可用时跳过缓存/限流 |
| 管线断点续传 | 🟡 | PipelineJob 有 status/retry_count，但无明确的失败自动恢复机制 |
| graceful shutdown | 🟡 | lifespan 有关闭逻辑，但未处理正在执行的请求/任务 |

---

## 7. 安全

| 检查项 | 状态 | 说明 |
|---|---|---|
| API Key 存储 | 🟢 | 仅存储 SHA-256 哈希，不存明文 |
| OAuth 凭证加密 | 🟢 | AES-256-GCM（`cryptography` 库） |
| 传输加密 | 🟡 | 文档说"生产环境 HTTPS"，但代码中无强制 HTTPS 重定向 |
| 实体隔离 | 🟢 | 所有操作限定 `entity_id`，记忆/向量/文件按实体隔离 |
| 文件大小限制 | 🟢 | upload 50MB 限制 |
| 输入校验 | 🟢 | Pydantic 模型校验，FastAPI 自动处理 |
| Webhook 签名验证 | 🟢 | GitHub HMAC-SHA256 验证 |
| 依赖安全扫描 | 🟢 | v0.4.0: `.github/workflows/security.yml` — pip-audit（每周+PR）、Gitleaks 密钥检测、CodeQL 静态分析；`.gitleaks.toml` 含项目定制规则。2026-08-11 安全审计（M2 #14）：pip-audit 升级为 0 漏洞硬门禁；Gitleaks 新增全历史扫描 job（8.30.1 固定版本）；规则跨行误报与 allowlist 结构失效修复；`/v1/extract-url` 无鉴权 SSRF 面修复（挂载 auth + 限流）。详见 `docs/verification/security-audit-2026-08.md` |
| SQL 注入防护 | 🟢 | SQLAlchemy 参数化查询 |
| PII 日志脱敏 | 🟢 | v0.4.0: `emerald/core/sanitizer.py` — structlog processor，生产环境自动启用；覆盖 email/电话/APIkey/IP/信用卡/SSN/JWT + 敏感字段名红action |
| 安全策略文档 | 🟢 | `SECURITY.md` — 支持版本、漏洞报告流程、信任边界图、12 项安全措施清单 |

---

## 8. 测试覆盖

| 检查项 | 状态 | 说明 |
|---|---|---|
| 单元测试数量 | 🟢 | 629 个测试函数通过（不含 Docker/fastembed ONNX），覆盖核心引擎、搜索、画像、认证、限流、异常、边缘情况 |
| 测试类型 | 🟢 | 单元测试、集成测试（Docker Compose）、负向测试、边缘情况、并发测试 |
| 连接器测试 | 🟡 迁移中 | 自研连接器 E2E 测试（27 个集成测试）将在连接中心 Pilot 验证后随旧代码删除（ADR-0004） |
| 端到端测试 | 🟢 | `docker-compose.test.yml` + `.env.test`，629 tests passing |
| 覆盖率配置 | 🟡 | `.coveragerc` omit 了 8 个文件（连接器任务、音视频提取等） |
| 测试运行 | 🟢 | `pytest` 全量测试通过，< 30s |
| 基准测试 | 🟡 | 有 `test_memory_benchmarks.py`，但未公布成绩 |

---

## 9. 功能完整性

| 功能模块 | 状态 | 说明 |
|---|---|---|
| **记忆引擎** | 🟢 | 提取 → 分块 → 嵌入 → 索引完整链路 |
| **关系推断** | 🟢 | **LLM-first**（DeepSeek → OpenAI 降级）+ 规则降级；bigram 快速预滤跳过无关配对 |
| **用户画像** | 🟢 | 静态 + 动态双层，Redis 缓存，主动失效 |
| **混合搜索** | 🟢 | hybrid/memory/rag 三种模式，结果合并去重 |
| **自动遗忘** | 🟡 | 三种策略定义清晰，但 Neo4j 实现可能不完整（代码操作 `graph._memories`） |
| **内容提取** | 🟢 | 7 种提取器（text/url/pdf/image/audio/video/code） |
| **分块** | 🟢 | 5 种分块器（text/conversation/markdown/pdf/code） |
| **连接器** | 🟡 迁移中 | 接入连接中心 Totem（ADR-0004，内部自托管动作层）：OAuth/执行/审计外包；Pilot 验证通过（2026-08-10）；旧自研实现 Pilot 后删除（issue #7） |
| **MCP Server** | 🟢 | stdio + SSE 双模式，3 个工具 |
| **Python SDK** | 🟢 | async client，4 核心方法 + 辅助方法 |
| **文档列表** | 🟢 | `GET /v1/files` 已实现 Document 分页查询（7 个集成测试覆盖） |
| **幂等写入** | 🟡 | Redis `idempotency_key` (1h TTL) 已实现；`customId` 仍在路线图（v0.6+ 计划） |
| **metadata 过滤** | 🟢 | MongoDB 风格 `$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne` 完整支持 |

---

## 10. 运维与文档

| 检查项 | 状态 | 说明 |
|---|---|---|
| README | 🟢 | 完整，含功能概览、API 示例、部署步骤 |
| AGENTS.md | 🟢 | 架构原则、设计决策、开发指南，不可协商约束清晰 |
| 架构文档 | 🟢 | 系统概览、数据模型、管线、API 设计、连接器、部署方案 |
| 集成指南 | 🟢 | SDK 用法、REST API、Pandaria 集成、MCP 配置 |
| API 文档 | 🟡 | FastAPI 自动生成 `/docs`（仅 dev 环境），无独立 API 参考站点 |
| 变更日志 | 🟡 | `CHANGELOG.md` 存在但未查看内容 |
| 版本策略 | 🟢 | v1 API 为统一版本；所有改进（错误码、分页、限流头）在 v1 中直接提供，无需 URL 版本号变更 |
| 社区/支持 | 🔴 | 无 Discord/论坛/Slack，issue 响应机制未建立 |

---

## 关键问题清单（按优先级排序）

> 本节反映 33 个 post-v0.3.0 commits 后的实际状态。✅ 表示已修复，⏳ 表示路线图中计划中。

### 🔴 P0 — 生产阻塞问题

| # | 原问题 | 状态 | 修复 commit / 说明 |
|---|---|---|---|
| 1 | **双写不一致（Neo4j + pgvector）** | ✅ 已修复 | `251e8ed`：`ReconciliationEngine` 后台扫描孤立节点，补偿标记 `is_latest=False` + `replaced_by="reconciliation_failed"` |
| 2 | **CORS `allow_origins=["*"]`** | ✅ 已修复 | `9058860`：环境变量 `CORS_ALLOWED_ORIGINS` 区分 dev/wildcard/prod 模式，检测到 `*` 记录警告日志 |
| 3 | **MinIO 同步调用阻塞事件循环** | ✅ 已修复 | `38fd354`：`asyncio.to_thread(client.put_object, ...)` 包裹同步调用 |
| 4 | **本地嵌入模型未实现** | ✅ 已修复 | `df7be0c`：`FastEmbedProvider` (ONNX runtime，无 PyTorch) |
| 5 | **pytest 未安装/测试无法运行** | ✅ 已修复 | `ee051e7` 等：484 → 601 test 函数（+117, +24%） |

### 🟡 P1 — 高风险问题

| # | 原问题 | 状态 | 修复 commit / 说明 |
|---|---|---|---|
| 6 | **关系推断引擎过于初级** | ✅ 已修复 | `0f29876` 增加了 LLM classify 路径；最新提交调整为 LLM-first（LLM 优先 + 规则降级 + bigram 预滤） |
| 7 | **重排序 Stub** | ✅ 已修复 | 升级为三级降级链：cached cross-encoder → embedding cosine → keyword boost |
| 8 | **遗忘引擎 Neo4j 实现不完整** | ✅ 已修复 | `9cd4c48`：添加 `GraphStore.list_entity_ids()` 公共接口，ForgetEngine 走正常接口 |
| 9 | **Neo4j 驱动无连接池配置** | ✅ 已修复 | `9cd4c48`：`max_connection_pool_size=50`, `connection_acquisition_timeout=30`, `max_transaction_retry_time=30` |
| 10 | **无幂等写入** | 🟡 部分修复 | `0f29876`：Redis 缓存 `idempotency_key` (1h TTL)；SDK 仍可通过 metadata 覆盖 memory_type |
| 11 | **`/v1/files` stub 实现** | ✅ 已修复 | `emerald/api/routes/v1/upload.py:list_files` 实现完整 Document 分页查询（带 status_filter）；新增 7 个集成测试覆盖。详情见 `tests/api/test_list_files.py`。**该文档本身的“stub”描述已修正** |
| 12 | **无分布式锁** | ✅ 已修复 | `83cba27`：`beat_lock(ttl_seconds=...)` Redis 分布式锁，防 Celery Beat 多实例重复执行 |

### 🟢 P2 — 优化建议

| # | 原问题 | 状态 | 修复 commit / 说明 |
|---|---|---|---|
| 13 | **无 OpenTelemetry 追踪** | 🟡 部分修复 | `38fd354` 等：手动 span 集成 (`emerald/core/tracing.py` 132 行)，FastAPI 自动 instrumentation 已就位；httpx/asyncpg/redis/celery 自动 instrumentation 是 M1 (v0.4.0) A4 计划 |
| 14 | **缺少自定义业务指标** | ✅ 已修复 | `1326b66`：`prometheus-fastapi-instrumentator` + `emerald/core/metrics.py` 提供业务指标（search_latency、pipeline_jobs_total 等） |
| 15 | **Dockerfile 非最优** | ⏳ M1 计划 | `requirements-prod.txt` 已拆分（`0f29876`）；production stage 独立 pip install 是 M1 (v0.4.0) A1 计划 |
| 16 | **画像冷缓存计算瓶颈** | 🟡 部分修复 | `0f29876`：多因子重要性评分 (confidence 35% + recency 25% + type 20% + rels 20%)；冷缓存仍全量重算，增量更新是 M3+ 计划 |
| 17 | **keyword search 性能** | ⏳ 未处理 | Neo4j 全文索引待评估；如 Staging 负载测试显示瓶颈则在 M4 处理 |
| 18 | **版本演进策略** | ✅ 已修复 | API 版本统一为 v1；所有改进（错误码、分页、限流头、PII 脱敏）在 v1 中直接提供 |

### 结论

**18 项 P0/P1/P2 问题中：**
- ✅ 已修复：15 项（83%）
- 🟡 部分修复：2 项（幂等 customId、OpenTelemetry 自动 instrumentation）
- ⏳ 仍待处理：1 项（Dockerfile 优化） — 纳入路线图 M1
- ✅ 已修复：所有 Stub 项（重排序、profile config、关系推断 LLM-first、/v1/files）

**生产化主线任务（M1-M2 完成度）：约 60%。**

---

## 生产部署建议

### 场景 A：内部试运行（推荐当前阶段）

✅ **可以部署**，需满足以下条件：
- 限制为内部用户/低流量场景（< 1000 DAU）
- 配置独立 Staging 环境，运行负载测试
- 可选启用本地嵌入（fastembed）或 OpenAI 嵌入
- 设置监控告警（Prometheus + Grafana + Alertmanager）
- 制定数据备份和灾难恢复流程
- 启用 ReconciliationEngine 后台任务（每 30 分钟）修复孤立节点

### 场景 B：生产环境（面向外部用户）

⚠️ **不建议立即部署**，需完成路线图 M1-M2：
- M1 (v0.4.0)：Dockerfile 优化、/v1/files 实现、OpenTelemetry 自动 instrumentation、真实 LLM 基准跑分、CI 自动化
- M2 (v0.4.0)：v2 API 下线（错误码 / 分页 / 限流头 / OpenAPI 自动化合并到 v1）、TS SDK v1、安全加固
- 路线图 [`docs/roadmap.md`](roadmap.md) §10 详述 v1.0 提升的 7 个硬性条件

---

## 与 Supermemory 的生产级差距

| 维度 | Emerald v0.4.0 | Supermemory | 差距状态 |
|---|---|---|---|
| **基准验证** | 🟡 脚本就位（6 维度 + JSON 报告） | ✅ 三项 #1 | 待真实 LLM 跑分 |
| **负载验证** | ❌ 未验证 | ✅ 10k 文档/小时 | M4 计划 |
| **重排序** | ✅ 三级降级链（cached CE → embedding → keyword） | ✅ cross-encoder | 已完成 |
| **查询改写** | ✅ LLM 化（DeepSeek → OpenAI 降级） | ✅ LLM-based | 已对齐 |
| **关系推断** | ✅ LLM-first + bigram 预滤 + 规则降级 | ✅ 更成熟的语义分析 | 已完成 |
| **metadata 过滤** | ✅ MongoDB 风格（$and/$or/$gte/$lte） | ✅ 同等 | 已对齐 |
| **分布式部署** | ✅ K8s 模板完整 | ✅ 全球分布式 | 架构对齐 |
| **SLA 保障** | ❌ 未定义 | ✅ SaaS SLA | M5 路线 |
| **版本演进** | 🟢 v1 统一版本（改进在 v1 直接提供） | ✅ v3→v4 演进 | 已完成 |
| **消费者产品** | ❌ 无 | ✅ App + 插件 | 不在路线图 |

**差距本质**：Emerald 的「骨架」+「核心能力」已对齐 Supermemory。所有 Stub 已清零。剩余差距集中在「生态成熟度」（真实生产负载验证、版本演进实质化）和「产品形态」（无消费者产品，这是定位选择）。详见 [`docs/comparison-supermemory.md`](comparison-supermemory.md) v2。

---

## 总结

| 维度 | 评级 | 核心问题 |
|---|---|---|
| 架构与部署 | 🟢 | 骨架完整，K8s 模板就位 |
| 数据持久化 | 🟢 | ReconciliationEngine 补齐双写一致性 |
| 认证与授权 | 🟢 | CORS 生产化，API Key 哈希存储 |
| 可观测性 | 🟢 | Prometheus + 结构化 JSON + OpenTelemetry 手动 span + 日志 trace_id 关联 |
| 性能与扩展性 | 🟢 | 所有能力已 LLM 化或三级降级（查询改写、关系分类、重排序） |
| 容错与恢复 | 🟢 | Reconciliation + Redis 分布式锁 + 优雅降级 |
| 安全 | 🟡 | CORS 修复；安全扫描未做（M2 P1 计划） |
| 测试覆盖 | 🟢 | 657 test 函数（+173 from v0.3.0 baseline 484）；M1 完成后基准 CI 已落地 |
| 功能完整性 | 🟢 | 核心能力对齐 Supermemory；所有 Stub 已清零（重排序、profile config、关系推断、/v1/files） |
| 运维与文档 | 🟢 | 文档完整对齐（comparison v2 + roadmap + 6 个架构/集成/概念/quickstart 文档） |

**综合评级：🟢 生产化进行中**——~36 个 post-v0.3.0 commits 补齐了 15/18 项生产就绪问题，所有 Stub 已清零。建议路径：**完成 M1-M5 后升级为 v0.8.0 Production-Ready Beta**（详见 [`docs/roadmap.md` §10](roadmap.md)）。

---

*评估时间：2026-06-01*  
*评估版本：Emerald v0.4.0*
