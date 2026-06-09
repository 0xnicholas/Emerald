# Spec: LLM 驱动的事实提取

> 日期：2026-06-09 | 版本：1.2 | 状态：已通过审查

## 1. 问题

Emerald 当前没有事实提取能力。所有 7 个提取器只做内容格式转换（PDF→文本、图片→OCR 等），`TextExtractor` 仅 `content.strip()`。输入一段对话，输出一整块原文，标记为 `memory_type="fact"`、`confidence=0.8`。结果：

- 图谱中没有细粒度结构化事实节点，只有原始文本块
- 所有记忆类型都是 "fact"（无法区分 fact/preference/episodic）
- 关系推断退化为文本相似度匹配（因为节点是整段对话而非单个事实）
- 搜索返回长段落而非可读的事实

这是 Emerald 与 Supermemory 最大的功能差距。

## 2. 目标

在管线中增加 LLM 驱动的事实提取，将一段对话/文本分解为多条结构化事实。改动封装在 Chunker 内部，管线其余阶段配合修改。

**范围：仅 `conversation` 和 `text` 两种 content_type 启用事实提取。** code/markdown/pdf 保持现有分块策略不变。

**成功标准：**
- 一段 10 句对话能提取 ≥ 3 条 fact + ≥ 1 条 episodic/preference
- 每条事实 `memory_type` 和 `confidence` 由 LLM 判定
- LLM 失败时优雅降级回当前的段落分块
- API key 未配置时自动跳过，不影响非 conversation/text 的管线

## 3. 设计

### 3.1 架构位置

```
管线：extract → chunk → embed → index → relationship → profile

        chunk 阶段
            │
    ┌───────┴────────┐
    │  FactExtractor  │  ← 新增：LLM 调用
    │  (可选)         │
    └───────┬────────┘
            │
    list[Chunk] → embed → ...
```

**选择放在 Chunker 而非 Extractor 的理由：**
- Extractor 职责：bytes→text（格式转换）
- Chunker 职责：text→list[Chunk]（分解为存储单元）
- LLM 事实提取的输入是 text，输出是 list[Chunk]，语义上属于 Chunker

### 3.2 核心接口

```python
@dataclass
class Fact:
    text: str              # 如 "Alex 在 Stripe 担任 PM"
    memory_type: str       # "fact" | "preference" | "episodic"
    confidence: float      # 0.0 - 1.0
    summary: str           # 短摘要（可选，用于搜索和画像展示）

class FactExtractor:
    """LLM 驱动的事实提取器基类"""
    async def extract(self, text: str, *, entity_context: str | None = None) -> list[Fact]:
        raise NotImplementedError
```

#### 3.2.1 Chunk dataclass 扩展

`Chunk` 需要新增三个字段以承载 LLM 提取的元数据，供下游 index 阶段使用：

```python
# emerald/pipeline/chunking/base.py — Chunk dataclass
@dataclass
class Chunk:
    text: str
    index: int
    token_count: int = 0
    content_type: str = "text"
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    # 新增：LLM 事实提取元数据
    memory_type: str = "fact"         # "fact" | "preference" | "episodic"
    confidence: float = 0.8           # 0.0 - 1.0
    summary: str = ""                 # 简短摘要
```

**默认值保持向后兼容**：未经过 FactExtractor 的 chunker（code/markdown/pdf）使用默认值，行为不变。

### 3.3 LLM 实现：DeepSeekFactExtractor

使用 DeepSeek V4-Flash，OpenAI 兼容 API。

```python
class DeepSeekFactExtractor(FactExtractor):
    def __init__(self, api_key: str, model: str = "deepseek-v4-flash"):
        ...

    async def extract(self, text, *, entity_context=None) -> list[Fact]:
        # 1. 构造 messages
        # 2. POST https://api.deepseek.com/chat/completions
        #    - response_format: { type: "json_object" }
        #    - temperature: 0.1
        #    - max_tokens: 2000
        # 3. 解析 JSON 响应（如 response_format 不支持，回退到剥离 code fence 后解析）
        # 4. 验证每条 Fact 字段（见 3.11）
        # 5. 返回 list[Fact]
```

**降级：** LLM 调用失败或 API key 未配置时，返回空列表，由 Chunker 回退到段落分块。

### 3.4 Prompt

```
SYSTEM:
你是事实提取引擎。从对话/文本中提取细粒度、独立的事实。
每条事实归入以下类型之一：

- fact：实体属性（工作、地点、技能、关系等）
- preference：偏好、习惯、倾向
- episodic：事件/互动记录（临时性）

规则：
1. 每条事实 1-2 句话，脱离上下文可独立理解
2. 不提取问候语、闲聊填充词、纯情感表达
3. 明确陈述 → confidence 0.8-0.95
4. 隐含可推断 → confidence 0.5-0.7
5. 新旧矛盾信息都提取——由关系引擎后续处理
6. 最多 20 条。无事实时返回空数组
7. summary 字段为 1 句话简短摘要（与原文保持相同语言），用于搜索/画像展示

输出严格 JSON：
{
  "facts": [
    {
      "text": "...",
      "type": "fact|preference|episodic",
      "confidence": 0.85,
      "summary": "..."
    }
  ]
}

---

USER:
[如有 entity_context]
上下文提示：{entity_context}

文本：
{text}
```

### 3.5 Chunker 改动

**ConversationChunker 改动：**

```python
class ConversationChunker(BaseChunker):
    def __init__(self, fact_extractor: FactExtractor | None = None):
        self.fact_extractor = fact_extractor

    async def chunk(self, text, content_type, metadata=None) -> list[Chunk]:
        # Phase 1: LLM 事实提取
        if self.fact_extractor:
            try:
                entity_context = (metadata or {}).get("entity_context")
                facts = await self.fact_extractor.extract(text, entity_context=entity_context)
                if facts:
                    return [
                        Chunk(
                            text=f.text,
                            index=i,
                            content_type="conversation",
                            memory_type=f.memory_type,
                            confidence=f.confidence,
                            summary=f.summary,
                            metadata=metadata,
                        )
                        for i, f in enumerate(facts)
                    ]
            except Exception:
                logger.warning("fact_extraction_failed", content_type="conversation", exc_info=True)

        # Phase 2: 回退 — 按轮次切割
        return self._chunk_by_turns(text, metadata)
```

**新增 SemanticTextChunker：**

`SemanticTextChunker` 继承 `TextChunker`，在其段落分块逻辑之上叠加 LLM 提取。这样 fallback 路径直接复用父类的 `chunk()` 方法。

```python
from emerald.pipeline.chunking.text import TextChunker

class SemanticTextChunker(TextChunker):
    """text 类型的 LLM 事实提取分块器。继承 TextChunker 以复用回退逻辑。"""

    def __init__(self, fact_extractor: FactExtractor | None = None, **kwargs):
        super().__init__(**kwargs)
        self.fact_extractor = fact_extractor

    async def chunk(self, text, content_type, metadata=None) -> list[Chunk]:
        if self.fact_extractor:
            try:
                entity_context = (metadata or {}).get("entity_context")
                facts = await self.fact_extractor.extract(text, entity_context=entity_context)
                if facts:
                    return [
                        Chunk(
                            text=f.text,
                            index=i,
                            content_type="text",
                            memory_type=f.memory_type,
                            confidence=f.confidence,
                            summary=f.summary,
                            metadata=metadata,
                        )
                        for i, f in enumerate(facts)
                    ]
            except Exception:
                logger.warning("fact_extraction_failed", content_type="text", exc_info=True)

        # Phase 2: 回退 — 父类的段落分块
        return await super().chunk(text, content_type, metadata)
```

### 3.6 注册与注入

```python
# emerald/api/app.py — _init_engine()

chunkers = ChunkerRegistry()

# 获取 FactExtractor（如果 API key 已配置）
fact_extractor = None
if settings.deepseek_api_key:
    from emerald.pipeline.chunking.fact_extractor import DeepSeekFactExtractor
    fact_extractor = DeepSeekFactExtractor(
        api_key=settings.deepseek_api_key,
        model=settings.fact_extraction_model,
    )

# 注入 fact_extractor
chunkers.register("conversation", ConversationChunker(fact_extractor=fact_extractor))
chunkers.register("text", SemanticTextChunker(fact_extractor=fact_extractor))

# 其他 chunker 不变
chunkers.register("code", CodeChunker())
chunkers.register("markdown", MarkdownChunker())
chunkers.register("pdf", PDFChunker())
```

### 3.7 配置

```python
# config.py 新增字段
class Settings:
    # DeepSeek
    deepseek_api_key: str = ""

    # 事实提取
    fact_extraction_model: str = "deepseek-v4-flash"
    fact_extraction_base_url: str = "https://api.deepseek.com"
    fact_extraction_max_facts: int = 20
    fact_extraction_timeout: float = 15.0
    fact_extraction_temperature: float = 0.1
    fact_extraction_max_tokens: int = 2000
```

### 3.8 异步支持

Chunker.chunk() 当前是同步方法。由于 LLM 调用是异步的，需要将 chunk 改为 async：

```python
# 改动前
class BaseChunker:
    def chunk(self, text, content_type, metadata=None) -> list[Chunk]: ...

# 改动后
class BaseChunker:
    async def chunk(self, text, content_type, metadata=None) -> list[Chunk]: ...
```

**完整的影响范围（所有需改动的调用点）：**

| 文件 | 改动 |
|---|---|
| `chunking/base.py` | `def chunk` → `async def chunk` |
| `chunking/registry.py` | `chunk()` → `async`，`run()` → `async`（`run` 是 `chunk` 的别名） |
| `chunking/text.py` | `TextChunker.chunk()` → `async` |
| `chunking/conversation.py` | `ConversationChunker.chunk()` → `async` |
| `chunking/code.py` | `CodeChunker.chunk()` → `async`（签名变更，无 LLM 调用） |
| `chunking/markdown.py` | `MarkdownChunker.chunk()` → `async` |
| `chunking/pdf.py` | `PDFChunker.chunk()` → `async` |
| `core/engine.py:112` | `self._chunk(...)` → `await self._chunk(...)` — **同步调用需改为 await** |
| `core/engine.py:186` | `_chunk()` → `async def _chunk`，内部 `await self.chunkers.chunk(...)` |
| `pipeline/tasks.py:93` | `chunker.chunk(text)` → `await chunker.chunk(text)` — **Celery 异步路径** |
| `pipeline/tasks.py:95-98` | chunk 序列化新增字段：`memory_type`、`confidence`、`summary` |
| `core/engine.py:130` | `memory_add_total.labels(memory_type="fact")` → 按 chunk 实际类型分别计数 |

**测试迁移：** 所有直接调用 `.chunk()` 的测试（约 50+ 个调用点分布在 ~8 个测试文件中）需要改为 `async def` + `await`。这是纯机械变更，但必须全部覆盖。

**重要实现细节：**
- Chunker 的 `chunk()` 方法保持 `**kwargs` 签名（`async def chunk(self, text: str, **kwargs)`），不从位置参数接收 `content_type` 或 `metadata`。LLM chunker 内部从 `kwargs` 中提取所需字段。这是与 registry.py 调用 `chunker.chunk(text, **kwargs)` 的兼容要求。
- `ConversationChunker` 的回退方法必须同时处理有/无说话人标注两种场景（当前 `_split_turns()` + `_chunk_by_size()` 两条路径）。

### 3.9 文件结构

```
emerald/pipeline/chunking/
├── __init__.py
├── base.py            # 改动：Chunk dataclass 新增 memory_type/confidence/summary；chunk() → async
├── registry.py        # 改动：chunk() 和 run() → async
├── fact_extractor.py  # 新增：FactExtractor + DeepSeekFactExtractor
├── conversation.py    # 改动：注入 FactExtractor；chunk() → async
├── text.py            # 改动：新增 SemanticTextChunker（继承 TextChunker）；TextChunker.chunk() → async
├── code.py            # 改动：chunk() → async（仅签名变更）
├── markdown.py        # 改动：chunk() → async（仅签名变更）
├── pdf.py             # 改动：chunk() → async（仅签名变更）
```

### 3.10 下游 index 阶段改动

当前两个 index 路径硬编码 `memory_type="fact"` 和 `confidence=0.8`，必须改为从 Chunk 读取。

**同步路径 — `emerald/core/engine.py:_index()`：**
```python
# 改动前
memory_id = await self.graph.create_memory(
    content=chunk.text,
    entity_id=entity_id,
    memory_type="fact",    # 硬编码
    confidence=0.8,        # 硬编码
    ...
)
# 改动后
memory_id = await self.graph.create_memory(
    content=chunk.text,
    entity_id=entity_id,
    memory_type=chunk.memory_type,   # 从 Chunk 读取
    confidence=chunk.confidence,     # 从 Chunk 读取
    summary=chunk.summary or None,   # 从 Chunk 读取
    ...
)
```

**异步路径 — `emerald/pipeline/tasks.py:_run_chunk()` 和 `_run_index()`：**

1. chunk 序列化新增字段：
```python
chunk_data = [
    {
        "id": c.id, "text": c.text, "index": c.index,
        "token_count": c.token_count,
        "memory_type": c.memory_type,     # 新增
        "confidence": c.confidence,       # 新增
        "summary": c.summary,             # 新增
    }
    for c in chunks
]
```

2. index 阶段从序列化数据读取：
```python
mid = await graph.create_memory(
    content=chunk_data["text"],
    entity_id=entity_id,
    memory_type=chunk_data.get("memory_type", "fact"),
    confidence=chunk_data.get("confidence", 0.8),
    summary=chunk_data.get("summary"),
    ...
)
```

**附加改动 — 指标计数：** `engine.py:130` 的 `memory_add_total.labels(memory_type="fact")` 需要改为按每个 chunk 的实际 `memory_type` 分别调用 `.inc()`，而非统一标记为 `"fact"`。

### 3.11 Fact 验证规则

`DeepSeekFactExtractor.extract()` 返回前对每条 LLM 输出执行验证：

| 字段 | 规则 | 违规处理 |
|---|---|---|
| `text` | 非空字符串 | 跳过该 fact |
| `type` | 必须是 `fact`、`preference`、`episodic` 之一 | 强制修正为 `fact` |
| `confidence` | 0.0 ≤ x ≤ 1.0 | 钳制到 [0.0, 1.0] |
| 重复检测 | 相同 text（标准化空白后） | 只保留第一条 |
| 条数上限 | 最多 `fact_extraction_max_facts`（默认 20） | 截断 |

无效 fact 记录 warning 日志但不阻塞管线。

## 4. 下游影响分析

| 管线阶段 | 改动 |
|---|---|
| Extract | ❌ 不变 |
| Chunk | ✅ 新增 FactExtractor + 扩展 Chunk dataclass + async 迁移 |
| Embed | ❌ 不变。输入仍为 list[Chunk] |
| Index (Graph) | ✅ 从 Chunk 读取 memory_type/confidence/summary（不再硬编码） |
| Index (Vector) | ❌ 不变 |
| Async Pipeline (tasks.py) | ✅ chunk 序列化新增字段，index 阶段读取新字段 |
| Relationship | ❌ 不变。细粒度事实上推断质量更高 |
| Profile | ❌ 不变。现在能真正区分 fact/preference/episodic |
| Search | ❌ 不变。返回细粒度事实可读性更好 |
| MCP Server | ❌ 不变 |
| SDK | ❌ 不变。add() 接口不变 |
| API routes | ❌ 不变 |

## 5. 降级路径

```
LLM 调用是否成功？
├── 是 → 返回 list[Fact] → 继续管线
│   └── list[Fact] 为空 → 回退段落分块
└── 否 → logger.warning → 回退段落分块
    ├── Timeout (15s) → 回退
    ├── API Error (4xx/5xx) → 回退
    ├── JSON 解析失败 → 回退
    └── response_format 不支持 → 回退到 content string 手动解析 JSON → 解析失败则回退
```

**每次降级都记录结构化日志**（fact_extraction_failed, reason=...），且不阻塞管线。

## 6. 测试策略

### 新增测试
- `DeepSeekFactExtractor.extract()` — mock httpx，测试 JSON 解析、字段验证、空响应、非法字段修正
- `SemanticTextChunker.chunk()` — mock FactExtractor，测试事实→Chunk 转换、回退到父类
- `ConversationChunker.chunk()` — mock FactExtractor，测试启用了 LLM 和未启用两种路径

### 现有测试迁移
约 50+ 个 `.chunk()` 同步调用需要改为 `await chunker.chunk(...)`（约 8 个测试文件）：
- `tests/unit/test_chunker_registry.py`
- `tests/pipeline/test_conversation_chunker.py`
- `tests/pipeline/test_text_chunker.py`
- `tests/pipeline/test_markdown_chunker.py`
- `tests/pipeline/test_code_chunker.py`
- `tests/pipeline/test_pdf_chunker.py`
- `tests/pipeline/test_default_registry.py`
- `tests/unit/test_conversation_chunking_markdown_bold.py`

这是机械变更但必须全量覆盖。

### 集成测试
- 端到端：add conversation → 验证图谱中有多条记忆节点，有不同的 memory_type
- 降级测试：API key 为空时整个管线仍正常工作
- Async 管线测试：Celery 路径下 chunk 序列化→反序列化字段完整性

### 负向测试
- LLM 返回非法 JSON → 回退无崩溃
- LLM 返回无效字段值 → 验证修正/跳过逻辑
- LLM 超时 → 回退无崩溃
- LLM 返回空 facts → 回退无崩溃
- LLM 返回超过 20 条 → 截断

## 7. 不在此 scope 的内容

- 图谱搜索的关系扩展（下一个 P0）
- 关系推断升级为语义理解（P1）
- 首选项强化（偏好随重复次数增强，P1）
- `entity_context` 参数的实际注入（当前 pipeline 中 metadata 为空的，entity_context 永远不会被填充——LLM prompt 中的上下文提示将始终为空）
- `valid_until` 自动推断（如从 "明天有考试" 中提取过期时间）
- LLM 调用并发控制（semaphore/队列）
- TypeScript SDK
- 框架集成
- 基准测试

## 8. 风险

| 风险 | 缓解 |
|---|---|
| LLM 提取质量不稳定 | temperature=0.1 增加确定性；结构化 JSON 输出强制格式；降级路径保证可用性 |
| LLM 延迟增加管线时间 | 15s 超时 + 降级；DeepSeek V4-Flash 快于大多数模型 |
| API 成本 | DeepSeek V4-Flash 极便宜（$0.14/M input），1K 字对话约 $0.0001 |
| async 迁移破坏现有测试 | 约 50+ 调用点，全部机械变更（`chunk()` → `await chunk()`）；逐个文件修改，逐文件验证 |
| `response_format: json_object` 兼容性 | 如果 DeepSeek 不支持此参数，回退到从 content string 中解析 JSON（strip code fences） |
| Prompt injection | `entity_context` 和 `text` 是用户输入直接注入 prompt。短期接受此风险（与 Supermemory 一致）；长期可考虑用 XML 标签隔离用户输入 |
| 并行 LLM 调用耗尽 API 额度 | 不在此 scope 内解决；后续可通过 semaphore 限制并发或批量调用 |
