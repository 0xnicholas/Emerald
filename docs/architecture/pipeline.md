# 处理管线

管线是 Emerald 的核心数据处理引擎，负责将原始内容（文本、文件、URL）转化为可搜索的知识图谱记忆。整个管线分为六个阶段，由 Celery 任务链驱动。

---

## 1. 管线状态机

```
                    ┌────────────────┐
                    │    QUEUED      │  任务创建，等待执行
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐
              ┌─────│   EXTRACTING   │  内容类型检测 + 提取
              │     └───────┬────────┘
              │             │
              │     ┌───────▼────────┐
              │     │   CHUNKING     │  语义分块
              │     └───────┬────────┘
              │             │
              │     ┌───────▼────────┐
              │     │   EMBEDDING    │  向量化
              │     └───────┬────────┘
              │             │
              │     ┌───────▼────────┐
              │     │   INDEXING     │  图谱关系构建 + 画像更新
              │     └───────┬────────┘
              │             │
              │     ┌───────▼────────┐
              │     │     DONE       │  可搜索
              │     └────────────────┘
              │
              │     任一阶段失败
              └──────► 重试 (最多 3 次)
                           │
                           ├── 成功 → 继续下一阶段
                           └── 耗尽 → FAILED + 写入死信
```

每个阶段的状态变更直接更新 `pipeline_jobs.status` 字段。

---

## 2. 管线入口

### 2.1 同步模式（轻量内容）

文本和对话等轻量内容可以在请求周期内同步处理，直接返回记忆 ID。

```python
# emerald/pipeline/orchestrator.py

async def process_sync(
    content: str,
    content_type: str,
    entity_id: str,
    metadata: dict | None = None,
) -> list[str]:
    """同步管线：适用于文本/对话等轻量内容"""
    pipeline_id = uuid4()
    logger.info("Pipeline started", pipeline_id=pipeline_id, entity_id=entity_id)

    try:
        # Stage 1: Extract
        extracted = await extract(content, content_type)
        # Stage 2: Chunk
        chunks = await chunk(extracted, content_type)
        # Stage 3: Embed (batch)
        embeddings = await embed([c.text for c in chunks])
        # Stage 4: Index
        memory_ids = await index_and_relate(chunks, embeddings, entity_id, metadata)
        # Stage 5: Update profile
        await update_profile(entity_id)

        logger.info("Pipeline complete", pipeline_id=pipeline_id, memory_count=len(memory_ids))
        return memory_ids
    except Exception as e:
        logger.error("Pipeline failed", pipeline_id=pipeline_id, error=str(e))
        raise
```

### 2.2 异步模式（文件/批量内容）

PDF、音视频等大文件通过 Celery 异步任务链处理，API 返回 `202 Accepted` + `pipeline_id`。

```python
# emerald/pipeline/orchestrator.py

async def process_async(
    content: str | bytes,
    content_type: str,
    entity_id: str,
    document_id: str | None = None,
) -> str:
    """异步管线：适用于文件/URL/批量内容"""
    pipeline_id = uuid4()
    content_hash = sha256(content.encode() if isinstance(content, str) else content).hexdigest()

    # 写入任务记录
    await db.execute(
        insert(PipelineJob).values(
            id=pipeline_id,
            entity_id=entity_id,
            document_id=document_id,
            content_hash=content_hash,
            status="queued",
        )
    )

    # 提交 Celery 链
    chain(
        extract_task.s(pipeline_id, content, content_type),
        chunk_task.s(),
        embed_task.s(),
        index_task.s(entity_id),
        postprocess_task.s(entity_id),
    ).apply_async()

    return pipeline_id
```

### 2.3 Celery 任务链

```python
# emerald/pipeline/tasks.py

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str):
    try:
        update_status(pipeline_id, "extracting")
        extracted_text = run_extractor(content, content_type)
        cache_set(f"pipeline:{pipeline_id}:extracted", extracted_text)
        return {"pipeline_id": pipeline_id, "content_type": content_type}
    except Exception as e:
        update_stage_error(pipeline_id, "extracting", str(e))
        raise self.retry(exc=e)

@app.task(bind=True, max_retries=2, default_retry_delay=30)
def chunk_task(self, prev_result: dict):
    pipeline_id = prev_result["pipeline_id"]
    content_type = prev_result["content_type"]
    try:
        update_status(pipeline_id, "chunking")
        extracted_text = cache_get(f"pipeline:{pipeline_id}:extracted")
        chunks = run_chunker(extracted_text, content_type)
        cache_set_json(f"pipeline:{pipeline_id}:chunks", [c.dict() for c in chunks])
        return {"pipeline_id": pipeline_id, "chunk_count": len(chunks)}
    except Exception as e:
        update_stage_error(pipeline_id, "chunking", str(e))
        raise self.retry(exc=e)

@app.task(bind=True, max_retries=3, default_retry_delay=30)
def embed_task(self, prev_result: dict):
    pipeline_id = prev_result["pipeline_id"]
    try:
        update_status(pipeline_id, "embedding")
        chunks = cache_get_json(f"pipeline:{pipeline_id}:chunks")
        texts = [c["text"] for c in chunks]
        embeddings = await provider.embed(texts)
        cache_set_json(f"pipeline:{pipeline_id}:embeddings", embeddings)
        return {"pipeline_id": pipeline_id}
    except Exception as e:
        update_stage_error(pipeline_id, "embedding", str(e))
        raise self.retry(exc=e)

@app.task(bind=True)
def index_task(self, prev_result: dict, entity_id: str):
    pipeline_id = prev_result["pipeline_id"]
    try:
        update_status(pipeline_id, "indexing")
        chunks = cache_get_json(f"pipeline:{pipeline_id}:chunks")
        embeddings = cache_get_json(f"pipeline:{pipeline_id}:embeddings")
        memory_ids = graph_indexer.index(chunks, embeddings, entity_id)
        return {"pipeline_id": pipeline_id, "memory_ids": memory_ids}
    except Exception as e:
        update_stage_error(pipeline_id, "indexing", str(e))
        raise

@app.task
def postprocess_task(prev_result: dict, entity_id: str):
    """管线后处理：关系推断 + 画像更新 + 遗忘检查"""
    pipeline_id = prev_result["pipeline_id"]
    memory_ids = prev_result.get("memory_ids", [])
    # 1. 为新记忆推断关系 (Update/Extend/Derive)
    infer_relationships_for(memory_ids, entity_id)
    # 2. 增量更新画像 (使缓存失效)
    invalidate_profile_cache(entity_id)
    # 3. 触发遗忘检查 (异步)
    schedule_forget_check(entity_id)
    # 4. 清理临时缓存
    cache_delete(f"pipeline:{pipeline_id}:extracted")
    cache_delete(f"pipeline:{pipeline_id}:chunks")
    cache_delete(f"pipeline:{pipeline_id}:embeddings")
    update_status(pipeline_id, "done")
```

---

## 3. 提取阶段 (EXTRACTING)

### 3.1 提取器注册表

```python
# emerald/pipeline/extraction/registry.py

EXTRACTORS: dict[str, type[BaseExtractor]] = {}

def register_extractor(content_type: str):
    def decorator(cls):
        EXTRACTORS[content_type] = cls
        return cls
    return decorator

def get_extractor(content_type: str) -> BaseExtractor:
    if content_type not in EXTRACTORS:
        raise UnsupportedContentType(f"No extractor for: {content_type}")
    return EXTRACTORS[content_type]()
```

### 3.2 基类接口

```python
# emerald/pipeline/extraction/base.py

class BaseExtractor(ABC):
    """提取器基类"""

    @abstractmethod
    async def extract(self, content: str | bytes, **kwargs) -> ExtractedContent:
        """提取内容为结构化文本"""
        ...

    @abstractmethod
    def supports(self, content_type: str) -> bool:
        """是否支持该内容类型"""
        ...
```

### 3.3 各提取器实现要点

#### 文本提取器

```python
@register_extractor("text")
class TextExtractor(BaseExtractor):
    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        # 文本直接透传，进行基本的清理
        cleaned = content.strip()
        if not cleaned:
            raise EmptyContentError("Content is empty after cleaning")
        return ExtractedContent(text=cleaned, metadata={})
```

#### URL 提取器

```python
@register_extractor("url")
class URLExtractor(BaseExtractor):
    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        # 1. 验证 URL 格式
        # 2. HTTP GET 获取内容（带 User-Agent、超时 30s）
        # 3. HTML 解析 → 去除 <script>、<style>、<nav>、<footer>
        # 4. 提取 <article> 或 <main> 或 <body> 文本
        # 5. readability-lxml / trafilatura 提取正文
        # 6. 返回清理后的纯文本 + 元数据（标题、作者、发布日期）
        ...
```

#### PDF 提取器

```python
@register_extractor("pdf")
class PDFExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        # 1. PyMuPDF 打开 PDF
        # 2. 逐页提取文本 + 表格
        # 3. 若无文本层，使用 Tesseract OCR 逐页识别
        # 4. 表格区域用 camelot/tabula 结构化提取
        # 5. 保留页面号和章节结构
        ...
```

#### 图片提取器

```python
@register_extractor("image")
class ImageExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        # 1. PIL 加载图片
        # 2. 预处理：灰度化、去噪、二值化
        # 3. Tesseract/PaddleOCR 文字识别
        # 4. 提取 OCR 置信度作为 metadata
        ...
```

#### 音频提取器

```python
@register_extractor("audio")
class AudioExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        # 1. 临时写入文件
        # 2. Faster-Whisper 加载模型（small/medium/large 按需）
        # 3. 转录音频为文本（支持语言检测）
        # 4. 检测说话人分段 (pyannote.audio)
        # 5. 返回带时间戳的转录文本 + 说话人标签
        ...
```

#### 视频提取器

```python
@register_extractor("video")
class VideoExtractor(BaseExtractor):
    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        # 1. 用 ffmpeg 抽离音轨
        # 2. 音频 → AudioExtractor → 转录文本
        # 3. 关键帧抽取 (每 N 秒一帧)
        # 4. 关键帧 → ImageExtractor → OCR 文本
        # 5. 按时间戳合并音频转录 + 帧文本
        ...
```

#### 代码提取器

```python
@register_extractor("code")
class CodeExtractor(BaseExtractor):
    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        language = kwargs.get("language", "auto")
        # 1. 若 language=auto，用 pygments 猜测语言
        # 2. tree-sitter 解析 AST（内置 Python/TS/JS/Go/Rust 支持）
        # 3. 提取函数签名、类定义、方法、导入
        # 4. 保留注释和文档字符串
        # 5. 返回结构化代码单元列表
        ...
```

### 3.4 提取错误处理

```python
class ExtractionError(Exception):
    def __init__(self, content_type: str, reason: str, retryable: bool = True):
        self.content_type = content_type
        self.reason = reason
        self.retryable = retryable

# 不可重试错误：
# - UnsupportedContentType → 直接 FAILED
# - EmptyContentError → 直接 FAILED
# - FileCorruptedError → 直接 FAILED

# 可重试错误：
# - Network timeout → 指数退避重试
# - OCR engine unavailable → 指数退避重试
# - Transcription model OOM → 指数退避重试
```

---

## 4. 分块阶段 (CHUNKING)

### 4.1 分块器注册表

```python
CHUNKERS: dict[str, type[BaseChunker]] = {}

def register_chunker(content_type: str):
    def decorator(cls):
        CHUNKERS[content_type] = cls
        return cls
    return decorator
```

### 4.2 基类接口

```python
class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        ...

    @property
    @abstractmethod
    def target_size(self) -> int:
        """目标分块大小 (tokens)"""
        ...

    @property
    @abstractmethod
    def overlap_size(self) -> int:
        """分块重叠大小 (tokens)"""
        ...
```

### 4.3 各分块策略

#### 文本分块

```python
@register_chunker("text")
class TextChunker(BaseChunker):
    target_size = 512       # tokens
    overlap_size = 64       # tokens (滑动窗口)

    def chunk(self, text: str) -> list[Chunk]:
        # 1. 按段落边界（\n\n）初步分割
        # 2. 按句子边界（。！？. ! ?）细分超长段落
        # 3. 合并过短的相邻段落（< 100 tokens）
        # 4. 相邻分块之间重叠 64 tokens
        # 5. 每个 chunk 记录字符偏移量
        ...

@register_chunker("conversation")
class ConversationChunker(BaseChunker):
    target_size = 512
    overlap_size = 0        # 对话不重叠

    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        # 1. 按说话人标签分割（"User:" / "Assistant:" / "System:"）
        # 2. 每轮对话为一个独立 chunk
        # 3. 保留说话人身份和轮次顺序
        # 4. 若单轮超长，再按句子分割
        ...
```

#### 代码分块

```python
@register_chunker("code")
class CodeChunker(BaseChunker):
    target_size = 0          # 不限，按结构
    overlap_size = 0

    def chunk(self, text: str, language: str = "auto") -> list[Chunk]:
        # 1. tree-sitter 解析 AST
        # 2. 按逻辑单元拆分：
        #    - import 语句 → 一块
        #    - 顶层函数 → 一块（含函数名 + 签名 + body 摘要）
        #    - 类 → 类定义一块 + 每个方法一块
        #    - 顶层变量/类型定义 → 归入 imports 块
        # 3. 每块的 content 包含所在类/模块名上下文
        # 4. chunk metadata 包含：function_name, class_name, line_range
        ...
```

#### Markdown 分块

```python
@register_chunker("markdown")
class MarkdownChunker(BaseChunker):
    target_size = 512
    overlap_size = 0

    def chunk(self, text: str) -> list[Chunk]:
        # 1. 按 # 标题层级构建文档树
        # 2. 每个 ## 节为一个 chunk（子标题合并到父节中）
        # 3. 每个 chunk 的 metadata 包含：标题路径 ["H1", "H2", "H3"]
        # 4. 若节正文超长（> 1024 tokens），按段落再细分
        # 5. 代码块保持为独立 chunk（不混入正文）
        ...
```

#### PDF 分块

```python
@register_chunker("pdf")
class PDFChunker(BaseChunker):
    target_size = 512
    overlap_size = 128        # PDF 上下文重要，增大重叠

    def chunk(self, text: str, structure: list[dict] | None = None) -> list[Chunk]:
        # 1. 利用 PDF 提取器提供的章节结构
        # 2. 按章节标题 + 段落边界切分
        # 3. 表格区域独立成块
        # 4. 相邻分块重叠 128 tokens（PDF 上下文敏感）
        # 5. metadata 包含页面号范围
        ...
```

### 4.4 分块输出模型

```python
class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    text: str                        # 分块文本
    index: int                       # 在文档中的顺序
    token_count: int                 # 估算 token 数
    content_type: str                # 来源内容类型
    metadata: dict = {}              # 类型特定元数据
    # 代码：{ function_name, class_name, line_range }
    # Markdown：{ heading_path, depth }
    # PDF：{ page_start, page_end, section_title }
    # 对话：{ speaker, turn_index }
```

---

## 5. 嵌入阶段 (EMBEDDING)

### 5.1 嵌入提供者

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成嵌入向量"""

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度"""

class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await openai_client.embeddings.create(
            model=self.model, input=texts
        )
        return [d.embedding for d in response.data]

class LocalBGEProvider(EmbeddingProvider):
    """本地 BGE 模型，无需外部 API"""
    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5"):
        self.model = FlagModel(model_name, ...)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()
```

### 5.2 嵌入缓存

为避免重复嵌入相同文本，引入基于文本哈希的缓存层：

```python
async def embed_with_cache(texts: list[str]) -> list[list[float]]:
    embeddings = []
    texts_to_embed = []
    cache_indices = []

    for i, text in enumerate(texts):
        text_hash = sha256(text.encode()).hexdigest()
        cached = await redis.get(f"embedding:{text_hash}")
        if cached:
            embeddings.append(json.loads(cached))
        else:
            texts_to_embed.append(text)
            cache_indices.append(i)
            embeddings.append(None)  # 占位

    if texts_to_embed:
        new_embeddings = await provider.embed(texts_to_embed)
        for idx, emb in zip(cache_indices, new_embeddings):
            embeddings[idx] = emb
            text_hash = sha256(texts[idx].encode()).hexdigest()
            await redis.setex(f"embedding:{text_hash}", 7*24*3600, json.dumps(emb))

    return embeddings
```

### 5.3 pgvector 写入

```python
async def store_embeddings(
    chunks: list[Chunk],
    embeddings: list[list[float]],
    document_id: str,
    entity_id: str,
    model_name: str,
):
    records = [
        {
            "chunk_id": chunk.id,
            "document_id": document_id,
            "entity_id": entity_id,
            "model_name": model_name,
            "dimensions": len(emb),
            "embedding": emb,  # pgvector 接受 list[float]
        }
        for chunk, emb in zip(chunks, embeddings)
    ]
    await db.execute(insert(Embedding), records)
```

---

## 6. 索引阶段 (INDEXING)

### 6.1 内存写入 Neo4j

```python
async def index_memories(
    chunks: list[Chunk],
    entity_id: str,
    document_id: str | None = None,
) -> list[str]:
    memory_ids = []
    async with neo4j.session() as session:
        for chunk in chunks:
            result = await session.run(
                """
                MATCH (e:Entity {id: $entity_id})
                CREATE (m:Memory {
                    id: $id, content: $content, summary: $summary,
                    memory_type: $memory_type, confidence: $confidence,
                    is_latest: true, valid_from: $valid_from,
                    source_document_id: $document_id,
                    source_type: $source_type,
                    tokens_estimate: $token_count,
                    created_at: datetime(), updated_at: datetime()
                })
                CREATE (e)-[:HAS_MEMORY {created_at: datetime()}]->(m)
                RETURN m.id
                """,
                id=str(uuid4()),
                content=chunk.text,
                summary=await generate_summary(chunk.text),
                memory_type=await classify_memory_type(chunk.text),
                confidence=0.8,
                valid_from=datetime.utcnow(),
                document_id=document_id,
                source_type="conversation" if chunk.content_type == "conversation" else "document",
                token_count=chunk.token_count,
                entity_id=entity_id,
            )
            memory_ids.append(await result.single())
    return memory_ids
```

### 6.2 关系推断

```python
async def infer_relationships(memory_ids: list[str], entity_id: str):
    """为新创建的记忆自动推断关系"""
    for memory_id in memory_ids:
        new_memory = await get_memory(memory_id)

        # 1. 在 pgvector 中搜索最相似的已有记忆
        similar_memories = await search_similar_memories(new_memory, entity_id, top_k=5)

        for existing in similar_memories:
            relation_type = await classify_relation(new_memory, existing)

            if relation_type == RelationType.UPDATES:
                await create_update_relation(new_memory, existing)
            elif relation_type == RelationType.EXTENDS:
                await create_extends_relation(new_memory, existing)

        # 2. 检查是否可从多条已有记忆推导出新事实
        derived_memories = await try_derive(memory_id, entity_id)
        for derived in derived_memories:
            await create_derives_from_relation(derived, memory_id)
```

### 6.3 UPDATES 关系的原子性保证

```python
async def create_update_relation(new_memory: Memory, old_memory: Memory):
    """创建更新关系 - 必须原子化"""
    async with neo4j.session() as session:
        # 单事务：三条操作原子化
        await session.run(
            """
            MATCH (new:Memory {id: $new_id})
            MATCH (old:Memory {id: $old_id})
            SET old.is_latest = false,
                old.replaced_by = $new_id,
                old.updated_at = datetime()
            CREATE (new)-[:UPDATES {
                created_at: datetime(),
                reason: $reason,
                confidence: $confidence
            }]->(old)
            """,
            new_id=new_memory.id,
            old_id=old_memory.id,
            reason=new_memory.update_reason or "contradiction",
            confidence=new_memory.confidence,
        )
```

---

## 7. 遗忘引擎

### 7.1 定时触发

```python
# Celery Beat 配置
app.conf.beat_schedule = {
    "forget-expired-memories": {
        "task": "emerald.pipeline.tasks.forget_expired",
        "schedule": crontab(minute=0),  # 每小时
    },
    "forget-noise-memories": {
        "task": "emerald.pipeline.tasks.forget_noise",
        "schedule": crontab(hour=3, minute=0),  # 每天凌晨 3 点
    },
    "decay-episodic-memories": {
        "task": "emerald.pipeline.tasks.decay_episodic",
        "schedule": crontab(hour=4, minute=0),  # 每天凌晨 4 点
    },
}
```

### 7.2 三类遗忘任务

```python
@app.task
def forget_expired():
    """时间过期遗忘"""
    async with neo4j.session() as session:
        await session.run(
            """
            MATCH (m:Memory)
            WHERE m.valid_until IS NOT NULL
              AND m.valid_until < datetime()
              AND m.is_latest = true
            SET m.is_latest = false,
                m.expired_at = datetime(),
                m.updated_at = datetime()
            """
        )

@app.task
def forget_noise(entity_id: str | None = None):
    """噪音过滤 - 低置信度且无关系的记忆"""
    # 条件：confidence < 0.3 AND 无 UPDATES/EXTENDS/DERIVES_FROM 关系 AND 创建超过 7 天
    ...

@app.task
def decay_episodic():
    """情节衰减"""
    # 情节记忆创建 > 30 天 → 降低搜索权重
    # 情节记忆创建 > 90 天 → 归档 (is_latest=False)
    ...
```

---

## 8. 可观测性

### 8.1 每条管线的日志规范

```json
{
    "event": "pipeline.stage_complete",
    "pipeline_id": "uuid",
    "entity_id": "entity_123",
    "stage": "indexing",
    "duration_ms": 340,
    "content_type": "pdf",
    "input_bytes": 204800,
    "chunk_count": 12,
    "memory_count": 8,
    "relationship_count": 3,
    "model_name": "text-embedding-3-small"
}
```

### 8.2 指标

| 指标名 | 类型 | 说明 |
|---|---|---|
| `pipeline_duration_seconds` | Histogram | 管线总耗时分布 |
| `pipeline_stage_duration_seconds` | Histogram | 各阶段耗时分布 |
| `pipeline_jobs_total` | Counter | 管线任务计数（按状态） |
| `pipeline_retries_total` | Counter | 重试次数 |
| `extraction_errors_total` | Counter | 提取错误（按类型） |
| `chunks_per_document` | Histogram | 每个文档的分块数分布 |
| `memories_per_entity` | Gauge | 每个实体的记忆数 |
| `forget_actions_total` | Counter | 遗忘操作计数（按策略） |
