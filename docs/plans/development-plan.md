# Emerald 开发计划

> 基于 [架构文档](../architecture/) 和 [AGENTS.md](../../AGENTS.md) 的完整实施路线图。

---

## 总体原则

1. **每阶段独立可交付和验证。** 一个阶段完成后，可以运行相关测试并演示增量功能。
2. **先走通最简单路径，再丰富边缘。** 文本 → 文件 → 多媒体 → 连接器。
3. **记忆 ≠ RAG。** 图谱和向量是两条独立路径，在 Step 8 合并。
4. **测试驱动。** 每个模块先写测试，再写实现。关系类型必须有确定性测试用例。
5. **所有阶段完成后运行完整测试套件。** 不累积技术债务。

---

## Phase 0: 项目骨架 ✅ 已完成

- [x] `pyproject.toml`、`requirements.txt`、`.env.example`
- [x] `emerald/config.py` — pydantic-settings 统一配置
- [x] `emerald/db/` — session / neo4j / redis / minio 连接工厂
- [x] `emerald/models/` — SQLAlchemy ORM 模型（Entity, ApiKey, Document, Connector, PipelineJob）
- [x] `emerald/core/` — 8 个模块接口 + 数据类（全部 TODO 标记）
- [x] `emerald/pipeline/` — orchestrator + tasks + extraction(7) + chunking(5)
- [x] `emerald/api/` — app + dependencies + 6 routes + 5 schemas
- [x] `emerald/connectors/` — base + registry + auth + 4 connector stubs
- [x] `tests/` `scripts/` `Dockerfile` `docker-compose.yml` `nginx.conf`

---

## Phase 1: 基础设施强化

**目标：数据库可迁移、日志可观测、错误处理统一、骨架代码可运行。**

### 1.1 数据库迁移 (Alembic)

| 文件 | 内容 |
|---|---|
| `migrations/alembic.ini` | Alembic 配置，指向 `emerald/models/base.py` |
| `migrations/env.py` | async migration runner |
| `migrations/versions/001_initial.py` | 初始 schema：entities, api_keys, documents, connectors, pipeline_jobs, embeddings |

**验收：** `alembic upgrade head` 在空 PostgreSQL 上成功创建所有表。

### 1.2 结构化日志

| 文件 | 内容 |
|---|---|
| `emerald/core/logging.py` | structlog 配置：JSONRenderer、上下文绑定、日志级别 |

**验收：** 导入 `logger` 后输出符合 schema 的结构化 JSON。

### 1.3 异常体系

| 文件 | 内容 |
|---|---|
| `emerald/core/exceptions.py` | 统一异常类：`EmeraldError` 基类 + `ExtractionError`、`EmbeddingError`、`PipelineError`、`NotFoundError` 等 |

**验收：** 每种异常可被 FastAPI exception handler 捕获并返回规范错误响应。

### 1.4 Celery 可启动

| 文件 | 内容 |
|---|---|
| `emerald/pipeline/celery.py` | Celery app 实例化，加载 broker + backend 配置 |
| `emerald/pipeline/tasks.py` | 完善 task 装饰器，注册 beat schedule |

**验收：** `celery -A emerald.pipeline.celery worker --loglevel=info` 成功启动并连接 Redis broker。

---

## Phase 2: 文本管线通跑（最简单的完整路径）

**目标：一句纯文本从 `add()` 进入，经提取→分块→嵌入→索引，最终可通过 `search()` 查回。**

### 2.1 TextExtractor 实现

| 文件 | 内容 |
|---|---|
| `emerald/pipeline/extraction/text.py` | 完整实现：strip、空内容检测、长度截断 |

**测试用例：**
- 正常文本 → 透传
- 空字符串 → `ExtractionError(retryable=False)`
- 纯空白 → `ExtractionError(retryable=False)`
- 多语言文本（中英混合）→ 保持原样

### 2.2 TextChunker 实现

| 文件 | 内容 |
|---|---|
| `emerald/pipeline/chunking/text.py` | 段落分割 → 句子细分 → 合并过短段落 → 滑动窗口重叠 |

**测试用例：**
- 短于 512 token 的单段文本 → 1 个 chunk
- 长文本 → N 个 chunk，每个不超过 512 tokens
- 相邻 chunk 重叠 64 tokens
- chunk.metadata 包含字符偏移量

### 2.3 OpenAI Embedding Provider 实现

| 文件 | 内容 |
|---|---|
| `emerald/core/embedder.py` | OpenAI API 调用、批次处理（max 2048 texts/batch）、重试 |

**测试用例：**
- 单文本 → 返回正确维度向量（1536 for text-embedding-3-small）
- 空文本列表 → 空列表
- API 超时 → 重试后成功或抛出 `EmbeddingError`
- 嵌入缓存命中 → 跳过 API 调用

### 2.4 pgvector 写入

| 文件 | 内容 |
|---|---|
| `emerald/core/vector.py`（新建） | `store_embeddings()`、`search_similar()`（向量相似度查询） |

**测试用例：**
- 写入嵌入 → 可从 pgvector 按 chunk_id 查回
- 相似度搜索 → 准确返回最相关的 chunks

### 2.5 Memory 写入 Neo4j

| 文件 | 内容 |
|---|---|
| `emerald/core/graph.py`（新建） | `create_memory()`、`get_memory()`、`list_latest_memories()` |

**测试用例：**
- 创建 Memory 节点 → 正确关联 Entity
- `is_latest=True` 且 `valid_from` 设置正确
- 查询最新记忆 → 按 `created_at DESC` 排序，仅返回 `is_latest=True`

### 2.6 集成测试：文本端到端

**测试场景：** `client.add(content="用户喜欢 TypeScript", entity_id="user_123")` → 等待管线完成 → `client.search(q="TypeScript", entity_id="user_123")` → 返回该记忆。

**验收：** Docker Compose 环境启动后，单个集成测试通过。

---

## Phase 3: 全部内容类型提取器

**目标：7 种 extractor 全部可工作（至少基本路径）。**

### 3.1 URL Extractor

- HTTP GET + trafilatura 正文提取 + 元数据（标题、作者、日期）
- 超时 30s，User-Agent 头
- 处理：301/302 重定向、404、超时

### 3.2 PDF Extractor

- PyMuPDF 文本提取
- 扫描件 Tesseract OCR 降级
- 表格区域标识（camelot）

### 3.3 Image Extractor

- PIL 预处理（灰度、去噪、二值化）
- Tesseract OCR
- 返回 OCR 置信度

### 3.4 Audio Extractor

- Faster-Whisper 转录
- 语言检测
- 可选说话人分离

### 3.5 Video Extractor

- ffmpeg 音轨提取 → AudioExtractor
- 关键帧 → ImageExtractor OCR
- 时间戳合并

### 3.6 Code Extractor

- tree-sitter AST 解析（Python/TS/JS/Go/Rust）
- 自动语言检测（pygments）
- 提取函数/类/方法签名 + 注释

### 3.7 对应 Chunker 实现

| Chunker | 依赖 |
|---|---|
| `conversation.py` | 说话人标签分割 |
| `code.py` | tree-sitter AST 单元 |
| `markdown.py` | # 标题层级树 |
| `pdf.py` | 章节结构 + 页号 |

**验收：** 每种 extractor + chunker 配对有独立测试。PDF 损坏不阻塞管线。

---

## Phase 4: 关系推断引擎

**目标：新记忆入图谱时自动创建 UPDATES / EXTENDS / DERIVES_FROM 关系。**

### 4.1 相似记忆搜索

- 新记忆嵌入 → pgvector 相似度查询 top-5 已有记忆
- 相似度阈值过滤（configurable）

### 4.2 关系分类

- UPDATES：LLM 或规则判断新旧事实矛盾
- EXTENDS：LLM 或规则判断新事实补充旧事实
- DERIVES_FROM：≥2 条已有事实推理出新事实

### 4.3 原子性 UPDATES 事务

**关键：** 单 Neo4j 事务中完成：`is_latest=False` + 创建 UPDATES 关系 + 设置 `replaced_by`

**测试用例（AGENTS.md 要求确定性）：**
- 事实 B 更新事实 A → A 的 `is_latest=False`，`replaced_by=B.id`
- 同一内容重复摄入 → 幂等，不创建重复关系
- A 扩展 B → 两者 `is_latest=True`
- 从 A+B 推导出 C → C 有 DERIVES_FROM 指向 A 和 B

---

## Phase 5: 画像管理

**目标：`GET /v1/profiles/{id}` 在 ~50ms 内返回静态 + 动态事实。**

### 5.1 画像计算

- Neo4j 查询：`is_latest=True` + `memory_type=fact/preference` → 静态
- Neo4j 查询：近期情节记忆（7 天内）+ 高置信度 → 动态

### 5.2 Redis 缓存

- Key: `profile:{entity_id}`
- TTL: 24h
- 写入路径：管线 INDEXING 后 → 计算 → 写 Redis
- 读取路径：先查 Redis → 未命中时查 Neo4j → 计算 → 回写
- 失效：新记忆摄入 → 删除对应缓存键

**验收：**
- 首次查询从 Neo4j 计算（允许 > 50ms）
- 后续查询从 Redis 命中（< 50ms）
- 新记忆摄入后缓存自动失效

---

## Phase 6: 混合搜索

**目标：单次查询同时返回 memory (Neo4j) + RAG (pgvector) 结果。**

### 6.1 Memory 搜索

- Neo4j 图谱遍历：按实体 → 最新记忆 → 文本匹配/关键词
- 过滤：`is_latest=True`、`valid_until` 未过期
- 得分：关系深度 + 置信度 + access_count 加权

### 6.2 RAG 搜索

- pgvector HNSW 索引 cosine 相似度
- 按 entity_id 过滤
- 返回分块 + 来源文档元数据

### 6.3 合并与排序

- 去重（同一内容在 memory 和 rag 均出现）
- 按 score 降序
- 截断到 top_k

### 6.4 可选增强

- 重排序（cross-encoder）：bge-reranker
- 查询改写：LLM 短查询扩展

**验收：**
- `search_mode=memory` → 仅返回个人记忆
- `search_mode=rag` → 仅返回文档 chunks
- `search_mode=hybrid` → 混合返回两者
- P99 响应 < 500ms

---

## Phase 7: 遗忘引擎

**目标：Celery Beat 定时任务自动执行 4 种遗忘策略。**

### 7.1 时间过期

- 每小时执行
- 查询 `valid_until < now()` 且 `is_latest=True`
- 设置 `is_latest=False`、`expired_at=now()`

### 7.2 噪音过滤

- 每天凌晨 3 点
- 条件：`confidence < 0.3` AND 无任何关系 AND 创建 > 7 天
- 移入 `archived` 状态

### 7.3 情节衰减

- 每天凌晨 4 点
- > 30 天：降低搜索权重
- > 90 天：`is_latest=False`

### 7.4 矛盾解决

- 已在 Phase 4（关系推断）中处理
- 不额外调度，在 UPDATES 创建时原子化完成

**验收：**
- 设置 `valid_until` 的记忆在过期后被标记
- 低置信度噪音在 7 天后被清理
- 旧情节记忆搜索权重随时间衰减

---

## Phase 8: API 层完整实现

**目标：所有端点的请求→处理→响应链路完整可调用。**

### 8.1 认证

- API Key 哈希验证（SHA-256）
- 权限检查（read/write/admin）
- 过期检测
- `last_used_at` 更新

### 8.2 端点实现

按优先级排序：

| 端点 | 优先级 | 依赖 |
|---|---|---|
| `GET /v1/health` | P0 | Phase 1 |
| `POST /v1/memories` (text) | P0 | Phase 2 |
| `POST /v1/search` | P0 | Phase 6 |
| `GET /v1/profiles/{id}` | P0 | Phase 5 |
| `GET /v1/memories/{id}` | P1 | Phase 2 |
| `DELETE /v1/memories/{id}` | P1 | Phase 2 |
| `POST /v1/upload` | P1 | Phase 3 |
| `GET /v1/pipelines/{id}` | P1 | Phase 2 |
| `GET /v1/files` | P2 | Phase 3 |
| Connector endpoints | P2 | Phase 10 |

### 8.3 中间件

- 速率限制（Redis sliding window）
- 请求 ID 注入
- 统一异常处理 → ErrorResponse

### 8.4 统一响应包装

- 成功：`{ "data": {...}, "meta": { "request_id": "...", "took_ms": N } }`
- 错误：`{ "error": { "code": "...", "message": "...", "details": {...} }, "meta": {...} }`

**验收：** Swagger UI 可交互测试所有 P0 端点。

---

## Phase 9: SDK 封装

**目标：Python SDK 提供与 REST API 一致的四个核心方法。**

| SDK 方法 | 对应端点 |
|---|---|
| `client.add(content, entity_id)` | `POST /v1/memories` |
| `client.search(q, entity_id)` | `POST /v1/search` |
| `client.profile(entity_id)` | `GET /v1/profiles/{id}` |
| `client.upload(file, entity_id)` | `POST /v1/upload` |

**验收：** SDK 方法签名、参数结构、返回类型与各语言 SDK 可一一对应。

---

## Phase 10: 连接器

**目标：至少 GitHub + Google Drive 可完成 OAuth 授权 → 增量同步 → Webhook 响应。**

### 10.1 GitHub Connector

- GitHub App OAuth flow
- Webhook 签名验证（HMAC-SHA256）
- 仓库文件同步（代码、Markdown、Issue）

### 10.2 Google Drive Connector

- Google Cloud OAuth flow
- Webhook channel 注册/续期
- 文件变更增量同步

### 10.3 Gmail / Notion

- 后续迭代（P1）

**验收：** OAuth 授权完成 → 文件自动同步 → 可通过 `search()` 查到同步内容。

---

## Phase 11: 记忆基准测试

**目标：在标准数据集上评估，对标 Supermemory。**

- LongMemEval 风格评估：长期记忆准确性
- LoCoMo 风格评估：对话一致性
- ConvoMem 风格评估：对话记忆召回

**验收：** 基准测试脚本可运行，产出量化指标（准确率、召回率、MRR）。

---

## Phase 12: 部署与可观测性

### 12.1 Docker Compose 验证

- 一键 `docker compose up` 启动全部服务
- 健康检查全部通过
- 文本摄入端到端在容器内可工作

### 12.2 K8s 部署

- ConfigMap + Secret + Deployment + Service + Ingress
- HPA 自动扩缩
- 备份 CronJob

### 12.3 监控

- Prometheus 指标端点（已预留 `/v1/metrics`）
- Grafana Dashboard 模板
- 告警规则（5xx 错误率、管线积压、缓存命中率）

### 12.4 日志采集

- 结构化 JSON 日志 → stdout
- Fluentd/Loki 采集（K8s 环境）

---

## 阶段依赖图

```
Phase 0 [DONE]
   │
Phase 1 (infra)
   │
Phase 2 (text pipeline) ── 最简单的端到端
   │
   ├── Phase 3 (all extractors + chunkers)
   ├── Phase 4 (relationships) ── 依赖 Phase 2 (Neo4j writes)
   ├── Phase 5 (profiles) ── 依赖 Phase 2 (Neo4j reads)
   │
Phase 6 (search) ── 依赖 Phase 2, 4
Phase 7 (forget) ── 依赖 Phase 2, 4
Phase 8 (API wire) ── 依赖 Phase 2-7
   │
Phase 9 (SDK) ── 依赖 Phase 8
Phase 10 (connectors) ── 依赖 Phase 2-3
Phase 11 (benchmarks) ── 依赖 Phase 2-7
Phase 12 (deploy) ── 可并行于 8-11
```

**Phase 2-7 可按团队并行推进**：extractors (3)、relationships (4)、profiles (5) 由不同开发者负责，合并到 search (6) 和 API (8)。

---

## 里程碑

| 里程碑 | 包含阶段 | 可演示内容 |
|---|---|---|
| M1: 最小可行记忆 | 0-2 | `add("用户喜欢TS", "user_123")` → `search("TS")` 返回该记忆 |
| M2: 全内容类型 | 0-3 | 上传 PDF/图片/代码 → 可搜索 |
| M3: 图谱智能 | 0-4,5,7 | 关系自动推断 + 画像 + 自动遗忘 |
| M4: 搜索完成 | 0-6 | 混合搜索（RAG + 记忆） |
| M5: API 就绪 | 0-8,9 | REST API + Python SDK 可用 |
| M6: 生态完成 | 0-10,11,12 | 连接器 + 基准测试 + 生产部署 |
