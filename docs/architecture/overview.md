# 系统概览

## 1. 架构分层

Emerald 采用四层架构：

| 层 | 职责 | 组件 |
|---|---|---|
| **客户端层** | 开发者交互入口 | Python SDK、REST API、Web 应用 |
| **API 网关层** | 请求路由、认证、限流 | FastAPI + 中间件 |
| **核心服务层** | 业务逻辑编排 | 记忆引擎、画像管理、混合搜索、连接器 |
| **数据层** | 持久化与缓存 | Neo4j、PostgreSQL/pgvector、MinIO、Redis |

---

## 2. 模块职责

### 2.1 记忆引擎 (`emerald/core/engine.py`)

系统的核心入口。所有摄入内容经由记忆引擎分发到处理管线。

- 接收 `content` (文本/文件/URL) + `entity_id`
- 检测内容类型，选择对应的提取器
- 编排管线阶段执行
- 返回管线状态和记忆 ID 列表

### 2.2 提取引擎 (`emerald/core/extractor.py`)

根据内容类型选择提取策略，将原始输入转化为结构化文本。

| 内容类型 | 提取策略 | 输出 |
|---|---|---|
| `text` | 直接透传 | 原文 |
| `url` | HTTP 抓取 → HTML 清洗（去除导航/广告/脚本）→ 正文提取 | 纯文本 |
| `pdf` | PyMuPDF/pdfplumber，扫描件用 Tesseract OCR | 文本 + 表格 |
| `image` | Tesseract/PaddleOCR 文字识别 | OCR 文本 |
| `audio` | Whisper/FasterWhisper 语音转文字 | 转录文本 |
| `video` | 抽取音频 → Whisper 转录 + 关键帧 OCR | 转录 + 帧文本 |
| `code` | tree-sitter AST 解析 → 提取函数/类/方法签名 | 结构化代码块 |

### 2.3 分块引擎 (`emerald/core/chunker.py`)

将提取后的文本拆分为语义完整的单元，为嵌入做准备。

| 内容类型 | 分块策略 | 目标大小 |
|---|---|---|
| `text` | 段落 + 句子界限分割，支持滑动窗口重叠 | 512-1024 tokens |
| `conversation` | 按对话轮次/用户消息分块，保留说话人信息 | 每轮一块 |
| `code` | tree-sitter AST 感知：函数、类、方法各为一块 | 函数级 |
| `markdown` | 按 `#` 标题层级切分，每段包含上下文标题 | 512-1024 tokens |
| `pdf` | 按 PDF 内置章节/标题分块，保留文档结构 | 512-1024 tokens |

### 2.4 嵌入引擎 (`emerald/core/embedder.py`)

将分块后的文本转化为向量。支持可插拔模型：

- `openai` — text-embedding-3-small / text-embedding-3-large
- `bge` — BAAI/bge-large-zh-v1.5 / bge-large-en-v1.5（本地部署）
- `text2vec` — shibing624/text2vec-base-chinese（本地部署）
- `custom` — 符合接口约定的任意嵌入服务

接口定义：
```python
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    def dimension(self) -> int: ...
```

### 2.5 关系推断引擎 (`emerald/core/relationship.py`)

在索引阶段，分析新记忆与图谱中已有记忆的关系，自动创建连接：

| 关系 | 触发条件 | 行为 |
|---|---|---|
| `UPDATES` | 新事实与旧事实在相同主题上矛盾 | 旧事实 `is_latest=False`，创建更新关系 |
| `EXTENDS` | 新事实补充旧事实的细节，不矛盾 | 两个事实均 `is_latest=True`，创建扩展关系 |
| `DERIVES` | 从 ≥2 条已有事实推理出新事实 | 创建新记忆节点，标注来源关系 |

### 2.6 画像管理 (`emerald/core/profile.py`)

维护每个实体的双层画像：

```
画像 = 静态事实 + 动态事实

静态事实（始终有效）:
  - 实体类型（用户/项目/组织）
  - 长期偏好（语言/工具/风格）
  - 稳定属性（职位/地点/技能）

动态事实（近期、情节性）:
  - 最近 N 次对话摘要
  - 当前工作项目/上下文
  - 最近关注的话题
```

- 画像在管线 INDEXING 阶段后增量更新，结果缓存至 Redis
- 读取接口直接从 Redis 读取，保证 ~50ms 内返回
- 缓存 TTL 默认 24h，摄入新内容时主动失效

### 2.7 混合搜索 (`emerald/core/search.py`)

编排三种搜索模式：

```
search_mode = "hybrid" → 同时执行 RAG 检索（pgvector）和记忆搜索（Neo4j）
                       → 结果去重、合并、按分数排序
search_mode = "memory" → 仅图谱遍历 + 时序过滤
search_mode = "rag"    → 仅向量相似度搜索
```

可选增强：
- `rerank=True` — 使用交叉编码模型（如 bge-reranker）对 Top-K 结果重排序
- `rewrite_query=True` — 使用 LLM 将短查询扩展为多关键词查询

### 2.8 遗忘引擎 (`emerald/core/forget.py`)

通过 Celery Beat 定时任务（默认每小时）触发，执行四类遗忘策略：

| 策略 | 触发条件 | 操作 |
|---|---|---|
| 时间过期 | `valid_until` 已过 | 标记 `is_latest=False`，设置 `expired_at` |
| 矛盾淘汰 | 已被 UPDATES 关系指向 | 保持历史记录但不在默认搜索中返回 |
| 噪音过滤 | `confidence < threshold` + 未被任何关系引用 | 移入 `archived` 状态 |
| 情节衰减 | `memory_type=episodic` + 创建超过 N 天 + 无 EXTENDS 关系 | 降低搜索权重，超过 2N 天后归档 |

### 2.9 连接器 (`emerald/connectors/`)

管理外部数据源的 OAuth 连接和同步。详见 [连接器架构](connectors.md)。

- 每个连接器实现统一的基类接口：`get_auth_url()` / `handle_callback()` / `sync()` / `handle_webhook()` / `revoke()`
- 同步调度由 Celery Beat 统一管理

### 2.10 管道编排器 (`emerald/pipeline/orchestrator.py`)

将提取、分块、嵌入、索引四个阶段串联为一个可恢复的异步管线。

---

## 3. 数据流

### 3.1 摄入数据流

```
客户端调用 POST /v1/memories { content, entity_id }
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│ FastAPI 路由层                                   │
│ - 验证 API Key → 确认 entity_id 归属            │
│ - 验证 content 大小/格式                        │
│ - 返回 202 Accepted + pipeline_id               │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ 管道编排器                                       │
│ - 创建 PipelineJob { id, status=QUEUED }        │
│ - 写入 PostgreSQL                                │
│ - 提交 Celery 任务链                             │
└────────────────────┬────────────────────────────┘
                     │ Celery chain
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    EXTRACTING   CHUNKING    EMBEDDING    INDEXING    DONE
    (提取)       (分块)      (嵌入)       (索引)      (完成)
```

### 3.2 搜索数据流

```
客户端调用 POST /v1/search { q, entity_id, search_mode }
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│ 混合搜索编排器                                   │
│                                                 │
│  ┌─────────────────┐   ┌──────────────────┐    │
│  │ RAG 路径         │   │ Memory 路径       │    │
│  │ pgvector 查询    │   │ Neo4j 图谱遍历    │    │
│  │ - 向量相似度     │   │ - 关系遍历        │    │
│  │ - 元数据过滤     │   │ - is_latest 过滤  │    │
│  │ - 得分排序       │   │ - 时序过滤        │    │
│  └────────┬────────┘   └────────┬─────────┘    │
│           │                     │               │
│           └──────┬──────────────┘               │
│                  ▼                              │
│          结果合并 / 去重 / 排序                  │
│          (可选) rerank 重排序                    │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
           返回 { results, profile }
```

### 3.3 画像读取数据流

```
客户端调用 GET /v1/profiles/{entity_id}
                    │
                    ▼
           ┌───────────────┐
           │  Redis 缓存    │
           │  key: profile: │
           │  {entity_id}   │
           │    命中?       │
           ├── 是 ─────────► 直接返回 (~50ms)
           │
           └── 否 ──► Neo4j 查询 ──► 计算画像 ──► 写入 Redis ──► 返回
```

---

## 4. 技术栈

| 类别 | 技术 | 版本 | 用途 |
|---|---|---|---|
| Web 框架 | FastAPI | ≥0.110 | REST API 服务 |
| 数据校验 | Pydantic | ≥2.0 | 请求/响应模型 |
| ORM | SQLAlchemy | ≥2.0 | PostgreSQL 数据访问 |
| 数据库迁移 | Alembic | ≥1.13 | 数据库版本管理 |
| 图数据库驱动 | neo4j | ≥5.20 | Neo4j 连接与管理 |
| 向量扩展 | pgvector | ≥0.7 | PostgreSQL 向量索引 |
| 文件存储 | minio | ≥7.2 | MinIO 客户端 |
| 缓存/队列 | redis | ≥5.0 | 缓存、Celery broker |
| 任务队列 | celery | ≥5.3 | 异步管线执行 |
| HTTP 客户端 | httpx | ≥0.27 | SDK 内部 HTTP 调用 |
| OCR | tesserocr / PaddleOCR | — | 图片文字识别 |
| 语音识别 | faster-whisper | ≥1.0 | 音频/视频转录 |
| PDF 解析 | PyMuPDF | ≥1.23 | PDF 文本提取 |
| 代码解析 | tree-sitter | ≥0.22 | AST 感知分块 |
| 嵌入模型 | openai / FlagEmbedding | — | 可插拔嵌入提供者 |
| ASGI 服务器 | uvicorn | ≥0.29 | 生产级 ASGI 服务 |
| 容器化 | Docker + Compose | — | 本地开发 / 部署 |
| 编排 | Kubernetes | — | 生产部署（可选） |

---

## 5. 关键设计约束

1. **所有外部调用必须有超时。** 嵌入 API 默认 30s，OAuth 回调默认 60s，Webhook 默认 10s。
2. **管线阶段可独立重试。** 每个阶段有自己的重试策略（次数、间隔、退避算法）。
3. **关系推断是幂等的。** 同一内容重复摄入不会创建重复关系。
4. **画像在摄入后增量更新。** 只在新增记忆可能影响画像时才重新计算。
5. **搜索响应时间目标。** 混合搜索 P99 < 500ms，画像读取 P99 < 100ms。

---

## 6. Post-v0.3.0 增强（2026-06-02 之后）

> 本节记录 v0.3.0 release (commit 2665734, 2026-06-01) 之后 33 个 commit 中的重大架构变更。未作为独立版本发布，将在路线图 v0.4 → v0.8 中逐步发布。完整 roadmap 见 [`docs/roadmap.md`](../roadmap.md)。

### 6.1 事实提取从「格式转换」升级为「语义理解」

**之前 (v0.3.0)：** 提取器只是格式转换（PDF→text, 图片→OCR），不进行 LLM 事实抽取。整段文本作为一个 chunk 存入图谱。

**之后 (Post-v0.3.0)：** 新增 LLM 驱动的事实提取层：

```
emerald/pipeline/chunking/fact_extractor.py
├─ FactExtractor          # 抽象基类
├─ DeepSeekFactExtractor  # 生产实现（OpenAI 兼容 API）
└─ get_fact_extractor()   # 工厂函数（无 API key 返回 None，走降级路径）
```

**工作流变化：**

```
v0.3.0:    原文 → chunks(N 个固定大小) → memory(N 个原文片段)
Post-v0.3.0: 原文 → fact extraction(LLM) → 多条结构化事实 → memory(每条事实 1 个)
```

**提取的每条事实包含：**
- `text`: 1-2 句可独立理解的陈述
- `memory_type`: `fact` | `preference` | `episodic`
- `confidence`: 0.0-1.0
- `summary`: 1 句话摘要（搜索/画像展示用）

### 6.2 图谱搜索从「平铺」升级为「关系遍历」

**之前：** 向量搜索命中 → is_latest + valid_until 过滤 → 返回。**已建立的关系从不参与搜索。**

**之后：** 新增 `_expand_relationships()` 阶段（`emerald/core/search.py`）：

```
搜索流程:
  1. 向量搜索找到 Top-K 记忆
  2. 对每个命中，沿 EXTENDS / DERIVES_FROM 关系双向深度=1 遍历
  3. 关联记忆以 0.85× 折扣分数并入结果集
  4. 重新排序 + 截断到 2× top_k
```

**效果：** 输入「用户在 Stripe 工作」可自动召回「用户领导 5 人支付团队」（EXTENDS 关系）。

### 6.3 关系推断新增 LLM 降级路径

**之前：** 仅关键词匹配 + 结构模板 + bigram 重叠。对隐含矛盾检测弱。

**之后：** 两阶段分类：

1. 规则路径（关键词、结构模板）— 快路径
2. LLM 路径（DeepSeek V4-Flash → OpenAI 降级）— 当规则结果为 NONE 时启用

### 6.4 首选项强化与语义去重

- **首选项强化**：当新偏好的 bigram 重叠 ≥ 0.3 与已有偏好时，已有偏好 confidence +0.05（上限 0.95），新记忆标记为 duplicate
- **语义去重**：bigram 快速过滤 + LLM 边界判定，避免重复记忆入库

### 6.5 本地嵌入（fastembed）

新增 `FastEmbedProvider`，使用 ONNX Runtime 提供本地嵌入，**无需 PyTorch / 无需 API key**：

```
emerald/core/embedder.py
├─ OpenAIProvider          # 云端
├─ FastEmbedProvider       # 本地（新增，零依赖 OpenAI）
├─ MockEmbeddingProvider   # 测试/CI
└─ get_embedding_provider() # 自动选择
```

**价值：** 完全离线运行 → 适合金融/医疗/政府等数据敏感场景。

### 6.6 多因子画像评分

**之前：** 画像排序使用单一维度（confidence）。

**之后：** 多因子加权评分：
```
importance = 0.35 × confidence
          + 0.25 × recency(指数衰减, 半衰期=30天)
          + 0.20 × type_weight(preference=1.0, fact=0.8, episodic=0.5, noise=0.2)
          + 0.20 × relationship_count(归一化到 [0,1])
```

### 6.7 生产可靠性组件

| 组件 | 作用 | 文件 |
|---|---|---|
| `ReconciliationEngine` | 后台修复 Neo4j 中无对应向量的孤立节点 | `emerald/core/reconciliation.py` |
| `beat_lock` | Redis 分布式锁，防止 Celery Beat 多实例并发 | `emerald/core/lock.py` |
| `GraphStore.update_memory_confidence()` | 原子置信度更新 | `emerald/core/graph.py` |
| `GraphStore.get_related_memories()` | 双向关系遍历 | `emerald/core/graph.py` |
| `GraphStore.list_entity_ids()` | 列出所有实体（修复 ForgetEngine 生产失效） | `emerald/core/graph.py` |
| `Neo4jDriver` | 连接池 50 + 超时 30s + 重试 30s | `emerald/db/neo4j.py` |

### 6.8 可观测性

- **OpenTelemetry 手动 span 集成**（`emerald/core/tracing.py`, 132 行）：FastAPI、Neo4j、httpx、Celery 自动 + 手动 span
- **结构化 JSON 日志** + Prometheus `/v1/metrics` 端点
- M1 (v0.4.0) 计划增加 OpenTelemetry 自动 instrumentation（httpx/asyncpg/redis/celery）

### 6.9 新 API 端点

| 端点 | 用途 |
|---|---|
| `POST /v1/memories/batch` | 批量写入最多 50 条 |
| `GET /v1/memories/graph` | 图谱节点+边可视化数据（D3/vis-network） |
| `DELETE /v1/memories/{id}` | 软删除（标记 `is_latest=False`） |
| MongoDB 风格 metadata 过滤（`$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne`） | 在 search 接口的 `filters` 参数中 |

### 6.10 基准测试套件升级

`scripts/run_benchmarks.py` 从 ~250 行扩展到 1154 行：

- 6 个评估维度：Fact Recall、Temporal Updates、Relationship Class、Profile Accuracy、Distractor Resist、Forgetting Correctness
- 对齐 LongMemEval / LoCoMo / ConvoMem 三大公开基准
- JSON 报告自动生成到 `reports/benchmark-YYYYMMDD-HHMMSS.json`

### 6.11 性能与稳定性优化

- `upload.py` 改用 `asyncio.to_thread` 包裹 MinIO 同步调用（修复 async 事件循环阻塞）
- CORS 生产加固（基于 `CORS_ALLOWED_ORIGINS` 环境变量区分 dev/prod）
- `engine.py` 全面 `async def` 化 + Celery 任务链异步化
- 移除 `raw_content_ref` dead code，改进 dedup 归一化
