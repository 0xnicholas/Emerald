# 数据模型

Emerald 采用四层数据模型：**图谱层** (Neo4j) 存储知识和关系，**关系层** (PostgreSQL) 存储结构化实体和配置，**向量层** (pgvector) 存储语义嵌入，**文件层** (MinIO) 存储原始二进制内容。

---

## 1. 图谱层 (Neo4j)

### 1.1 节点类型

#### Entity（实体节点）

```
(:Entity {
    id: String,            # UUID，唯一标识
    external_id: String,   # 外部系统 ID（如应用的用户 ID）
    type: String,          # "user" | "project" | "organization" | "custom"
    name: String,          # 实体名称
    metadata_json: String, # JSON 扩展字段
    created_at: DateTime
})

约束：UNIQUE(id), INDEX(external_id, type)
```

#### Memory（记忆节点）

知识图谱的核心单元，每一条被提取的事实对应一个 Memory 节点。

```
(:Memory {
    id: String,               # UUID
    content: String,          # 记忆内容文本
    summary: String,          # LLM 生成的简要摘要
    memory_type: String,      # "fact" | "preference" | "episodic"
    confidence: Float,        # 置信度 (0.0-1.0)
    is_latest: Boolean,       # 是否为最新版本
    valid_from: DateTime,     # 事实生效时间
    valid_until: DateTime,    # 事实失效时间（临时事实使用）
    expired_at: DateTime,     # 实际过期处理时间（由遗忘引擎设置）
    replaced_by: String,      # 取代此记忆的最新记忆 ID
    source_document_id: String, # 来源文档 ID
    source_type: String,      # "conversation" | "document" | "file" | "inferred"
    tokens_estimate: Integer, # 估算 token 数
    access_count: Integer,    # 被检索次数（用于热度排序）
    last_accessed_at: DateTime,
    created_at: DateTime,
    updated_at: DateTime
})

约束：UNIQUE(id), INDEX(memory_type), INDEX(is_latest), INDEX(valid_until)
```

#### Document（文档节点）

原始文档在图谱中的表示。

```
(:Document {
    id: String,
    title: String,            # 文档标题
    content_type: String,     # "pdf" | "image" | "audio" | "video" | "code" | "markdown" | "url"
    storage_key: String,      # MinIO 存储路径
    file_size_bytes: Integer,
    page_count: Integer,      # PDF 页数（如适用）
    duration_seconds: Integer,# 音视频时长（如适用）
    status: String,           # "queued" | "processing" | "done" | "failed"
    created_at: DateTime
})
```

#### Chunk（分块节点）

文档在嵌入前被拆分为的分块单元。

```
(:Chunk {
    id: String,
    content: String,          # 分块文本
    chunk_index: Integer,     # 在文档中的顺序
    token_count: Integer,
    embedding_ref: String,    # pgvector 中对应嵌入的引用（或直接在这里存向量引用）
    created_at: DateTime
})
```

### 1.2 关系类型

#### HAS_MEMORY（实体 → 记忆）

```
(:Entity)-[:HAS_MEMORY { created_at: DateTime }]->(:Memory)
```

每个实体拥有多个记忆。这是最基础的关系。

#### HAS_DOCUMENT（实体 → 文档）

```
(:Entity)-[:HAS_DOCUMENT { created_at: DateTime }]->(:Document)
```

#### HAS_CHUNK（文档 → 分块）

```
(:Document)-[:HAS_CHUNK { created_at: DateTime }]->(:Chunk)
```

#### FROM_DOCUMENT（记忆 → 文档）

```
(:Memory)-[:FROM_DOCUMENT { created_at: DateTime }]->(:Document)
```

追踪记忆的原始来源。

#### UPDATES（记忆 → 记忆）

```
(:Memory)-[:UPDATES {
    created_at: DateTime,
    reason: String,      # "contradiction" | "correction" | "temporal_change"
    confidence: Float
}]->(:Memory)
```

方向：新记忆 → 旧记忆。「新信息取代旧信息」。

约束：
- 创建 UPDATES 前，目标记忆的 `is_latest` 必须设为 `False`
- 源记忆的 `is_latest` 必须为 `True`
- 目标记忆的 `replaced_by` 必须设为源记忆的 `id`
- 以上操作在同一事务中完成

#### EXTENDS（记忆 → 记忆）

```
(:Memory)-[:EXTENDS {
    created_at: DateTime,
    aspect: String       # 扩展的方面，如 "detail" | "context" | "example"
}]->(:Memory)
```

方向：新记忆 → 被扩展的已有记忆。「新信息补充原有信息」。

约束：
- 两个记忆的 `is_latest` 同时为 `True`
- 不能有 UPDATES 和 EXTENDS 同时指向同一对记忆

#### DERIVES_FROM（推导记忆 → 源记忆）

```
(:Memory)-[:DERIVES_FROM {
    created_at: DateTime,
    reasoning: String    # 推理过程的简要说明
}]->(:Memory)
```

方向：推导出的新记忆 → 作为推理基础的已有记忆。一个推导记忆可以指向多条源记忆。

### 1.3 图谱查询示例

查询某实体的所有最新记忆：

```cypher
MATCH (e:Entity {id: $entity_id})-[:HAS_MEMORY]->(m:Memory)
WHERE m.is_latest = True
  AND (m.valid_until IS NULL OR m.valid_until > datetime())
RETURN m
ORDER BY m.created_at DESC
LIMIT $limit
```

查询某记忆的完整演进历史：

```cypher
MATCH path = (newest:Memory {id: $memory_id})-[:UPDATES*0..]->(oldest:Memory)
WHERE NOT (oldest)-[:UPDATES]->()
RETURN [node IN nodes(path) | node.id] AS history
```

查询某记忆的上下文（扩展和来源）：

```cypher
MATCH (m:Memory {id: $memory_id})-[:EXTENDS|DERIVES_FROM*1..2]-(related:Memory)
RETURN related
```

---

## 2. 关系层 (PostgreSQL)

### 2.1 实体表

```sql
CREATE TABLE entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     VARCHAR(255) NOT NULL,
    type            VARCHAR(50) NOT NULL CHECK (type IN ('user', 'project', 'organization', 'custom')),
    name            VARCHAR(255) NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(external_id, type)
);

CREATE INDEX idx_entities_external_id ON entities(external_id);
```

### 2.2 API 密钥表

```sql
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    key_hash        VARCHAR(255) NOT NULL UNIQUE,  -- SHA-256 hash
    key_prefix      VARCHAR(8) NOT NULL,           -- em_xxxxxx (用于前端展示)
    permissions     TEXT[] DEFAULT '{}',            -- ["read", "write", "admin"]
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT valid_key_prefix CHECK (key_prefix LIKE 'em_%')
);

CREATE INDEX idx_api_keys_entity ON api_keys(entity_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
```

API Key 格式：`em_` + 32 字符随机字符串。服务端仅存储 SHA-256 哈希。

### 2.3 文档元数据表

```sql
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    content_type    VARCHAR(50) NOT NULL,
    storage_key     VARCHAR(500) NOT NULL,          -- MinIO 对象键
    file_size_bytes BIGINT,
    page_count      INTEGER,
    duration_seconds INTEGER,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    error_message   TEXT,
    chunk_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_entity ON documents(entity_id);
CREATE INDEX idx_documents_status ON documents(status);
```

### 2.4 连接器表

```sql
CREATE TABLE connectors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,            -- "google_drive" | "gmail" | "notion" | "github"
    credentials     BYTEA NOT NULL,                  -- 加密后的 OAuth token
    webhook_secret  VARCHAR(255),
    sync_status     VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (sync_status IN ('active', 'paused', 'revoked', 'error')),
    last_synced_at  TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(entity_id, provider)
);

CREATE INDEX idx_connectors_entity ON connectors(entity_id);
```

`credentials` 字段使用 AES-256-GCM 加密存储，密钥通过环境变量注入。

### 2.5 管线任务表

```sql
CREATE TABLE pipeline_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    document_id     UUID REFERENCES documents(id),
    content_hash    VARCHAR(64) NOT NULL,            -- SHA-256 (用于去重)
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'extracting', 'chunking', 'embedding', 'indexing', 'done', 'failed')),
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pipeline_jobs_entity ON pipeline_jobs(entity_id);
CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status);
```

### 2.6 画像缓存表

```sql
CREATE TABLE profile_cache (
    entity_id       UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    static_facts    JSONB NOT NULL DEFAULT '[]',     -- [{content, importance, updated_at}]
    dynamic_facts   JSONB NOT NULL DEFAULT '[]',     -- [{content, relevance, updated_at}]
    computed_at     TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1
);
```

### 2.7 实体设置表

```sql
CREATE TABLE entity_settings (
    entity_id       UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    settings        JSONB NOT NULL DEFAULT '{}',     -- 灵活配置
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 3. 向量层 (pgvector)

### 3.1 嵌入表

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id        UUID NOT NULL,                    -- 对应 Chunk 节点
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    model_name      VARCHAR(100) NOT NULL,            -- 嵌入模型名称
    dimensions      INTEGER NOT NULL,                 -- 向量维度
    embedding       vector(4096),                     -- 向量（最大 4096 维，可动态调整）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW 索引（生产环境推荐）
CREATE INDEX idx_embeddings_hnsw ON embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- 用于精确搜索的 IVFFlat 索引（备选）
-- CREATE INDEX idx_embeddings_ivfflat ON embeddings
--     USING ivfflat (embedding vector_cosine_ops)
--     WITH (lists = 100);

CREATE INDEX idx_embeddings_entity ON embeddings(entity_id);
CREATE INDEX idx_embeddings_document ON embeddings(document_id);
```

### 3.2 向量索引策略

| 索引类型 | 构建速度 | 搜索速度 | 精度 | 适用场景 |
|---|---|---|---|---|
| IVFFlat | 快 | 中 | 高 (95%+) | 开发/小数据量 |
| HNSW | 慢 | 快 | 高 (99%+) | 生产/大数据量 |

推荐：开发环境用 IVFFlat（快速迭代），生产环境使用 HNSW。

### 3.3 可插拔嵌入模型配置

```python
# 嵌入模型维度参考
EMBEDDING_CONFIGS = {
    "openai/text-embedding-3-small":   1536,
    "openai/text-embedding-3-large":   3072,
    "BAAI/bge-large-zh-v1.5":         1024,
    "BAAI/bge-large-en-v1.5":         1024,
    "BAAI/bge-m3":                    1024,
    "shibing624/text2vec-base-chinese": 768,
}
```

迁移策略：当更换嵌入模型时，创建新的 `embeddings` 分区（按 `model_name` 过滤），逐步重新嵌入，切换后废弃旧索引。

---

## 4. 文件层 (MinIO)

### 4.1 存储路径规则

```
{bucket}/{entity_id}/{document_id}/{filename}
```

示例：
```
emerald-documents/user_abc123/doc_a1b2c3/report.pdf
emerald-documents/project_xyz/doc_d4e5f6/screenshot.png
```

### 4.2 Bucket 设计

| Bucket | 用途 | 生命周期策略 |
|---|---|---|
| `emerald-documents` | 用户上传的原始文件 | 保留至实体删除 |
| `emerald-temp` | 管线处理中的临时文件 | 24h 自动过期 |

### 4.3 文件接口

```python
class FileStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def presigned_get_url(self, key: str, expires: int = 3600) -> str: ...
    async def presigned_put_url(self, key: str, expires: int = 3600) -> str: ...
```

### 4.4 安全策略

- 用户文件隔离：通过 `entity_id` 路径前缀实现租户隔离
- 签名 URL：所有文件访问通过预签名 URL（默认 1 小时过期），不直接暴露 MinIO
- 上传限制：单文件最大 50MB，通过 API 网关限流
- 内容扫描：上传后校验 MIME 类型和白名单

---

## 5. 缓存层 (Redis)

### 5.1 缓存键设计

```
profile:{entity_id}            → 画像数据（JSON），TTL 24h
session:{session_id}           → 会话状态，TTL 30m
rate_limit:{api_key}:{window}  → 速率限制计数器，TTL = window
embedding:{hash}               → 嵌入缓存（避免重复计算），TTL 7d
pipeline_lock:{job_id}         → 管线任务分布式锁，TTL 5m
```

### 5.2 画像缓存更新策略

```
写入路径：管线 INDEXING 阶段 → 比较新旧画像差异 → 有变更时写入 Redis
读取路径：GET /v1/profiles/{id} → 先查 Redis → 未命中时查 PG + Neo4j → 计算 → 回写 Redis
失效策略：新记忆创建后 → 删除对应 entity 的 profile 缓存键
```

---

## 6. 数据一致性保证

| 操作 | 一致性策略 | 说明 |
|---|---|---|
| 记忆创建 | Neo4j + pgvector 写入在同一 Celery 任务中顺序执行 | 最终一致性，失败可重试 |
| UPDATES 关系 | Neo4j 事务：设置 `is_latest=False` + 创建关系 + 设置 `replaced_by` | 强一致性（图数据库事务） |
| 画像更新 | Redis 缓存 + PostgreSQL 持久化双写 | 先写 PG，再写 Redis，失败回滚 |
| 文件上传 | MinIO 写入 → 成功后写 PG documents 表 | 先存储，后索引 |
| 连接器同步 | 每个文件的摄取作为独立管线任务 | 隔离失败，不影响其他文件 |

---

## 7. Post-v0.3.0 数据模型增强（2026-06-02 之后）

> 本节记录 v0.3.0 之后 33 个 commit 中影响数据模型的重要变更。详见 [`docs/roadmap.md`](../../roadmap.md)。

### 7.1 Memory 节点新增字段（LLM 事实提取使能）

原 Memory 节点设计在 v0.3.0 中为 `memory_type`、`confidence`、`summary` 预留了字段，但 Post-v0.3.0 由 LLM 实际填充：

```
(:Memory {
    ...原有字段...
    summary: String,           # 【真正填充】LLM 生成的 1 句话摘要（搜索/画像展示用）
    memory_type: String,       # 【真正填充】"fact" | "preference" | "episodic"
    confidence: Float,         # 【真正填充】LLM 评分 0.0-1.0
    importance: Float,         # 【新增】多因子评分 0.0-1.0（见 7.3）
})
```

**三级字段填充路径：**

| 路径 | memory_type 来源 | confidence 来源 | 适用场景 |
|---|---|---|---|
| LLM 提取（默认） | DeepSeek 分类 | DeepSeek 评分 | 启用 `DEEPSEEK_API_KEY` 后 |
| LLM 提取（降级） | OpenAI 分类 | OpenAI 评分 | 仅有 `OPENAI_API_KEY` 时 |
| 无 LLM（传统） | 默认 `fact` | 硬编码 0.8 | 无 API key 或提取失败 |

### 7.2 Chunk 中间产物字段

`emerald/pipeline/chunking/base.py:Chunk` 数据类扩展：

```python
@dataclass
class Chunk:
    text: str                          # 块文本
    metadata: dict[str, Any]           # 位置/类型元数据
    memory_type: str = "fact"          # 【新增】从 LLM 提取结果继承
    confidence: float = 0.8            # 【新增】从 LLM 提取结果继承
    summary: str = ""                  # 【新增】从 LLM 提取结果继承
```

**价值：** Chunk 与最终 Memory 节点字段一一对应，便于调试与可观测。

### 7.3 importance 多因子评分

Post-v0.3.0 新增 `importance` 字段（`emerald/core/profile.py:_compute_importance`）：

```
importance = 0.35 × confidence
          + 0.25 × recency(指数衰减, half_life=30天)
          + 0.20 × type_weight(preference=1.0, fact=0.8, episodic=0.5, noise=0.2)
          + 0.20 × relationship_count(归一化到 [0,1])
```

**与 confidence 的区别：** confidence 反映来源可信度（LLM 评分）；importance 反映「该记忆当前的相关度」。

### 7.4 Neo4j 索引

新增索引（Post-v0.3.0）：

```cypher
CREATE INDEX memory_importance IF NOT EXISTS FOR (m:Memory) ON (m.importance);
CREATE INDEX memory_confidence IF NOT EXISTS FOR (m:Memory) ON (m.confidence);
```

### 7.5 Reconciliation 元数据

孤立节点补偿：`ReconciliationEngine` (`emerald/core/reconciliation.py`) 扫描最近 N 个图谱节点，检查向量表是否存在匹配行，缺失则标记 `is_latest=False` + `replaced_by="reconciliation_failed"`。

### 7.6 Redis 锁键

新增 `beat_lock:{task_name}` 键，用于 Celery Beat 多实例并发防护（`emerald/core/lock.py`）。协议：`SET key instance-id NX EX ttl` 自动释放。

### 7.7 PipelineJob 新字段

```python
class PipelineJob:
    id: str
    status: str                # QUEUED | EXTRACTING | CHUNKING | EMBEDDING | INDEXING | DONE | FAILED
    content_type: str          # 【Post-v0.3.0】记录实际提取路径
    entity_id: str
    memory_ids: list[str]      # 【Post-v0.3.0】可能包含多个 memory_id（LLM 提取后多事实）
    fact_extraction_status: str  # 【Post-v0.3.0】"success" | "failed" | "skipped"
```
