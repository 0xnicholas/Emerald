# Spec: LLM 驱动的事实提取

> 日期：2026-06-09 | 版本：1.0 | 状态：待审查

## 1. 问题

Emerald 当前没有事实提取能力。所有 7 个提取器只做内容格式转换（PDF→文本、图片→OCR 等），`TextExtractor` 仅 `content.strip()`。输入一段对话，输出一整块原文，标记为 `memory_type="fact"`、`confidence=0.8`。结果：

- 图谱中没有细粒度结构化事实节点，只有原始文本块
- 所有记忆类型都是 "fact"（无法区分 fact/preference/episodic）
- 关系推断退化为文本相似度匹配（因为节点是整段对话而非单个事实）
- 搜索返回长段落而非可读的事实

这是 Emerald 与 Supermemory 最大的功能差距。

## 2. 目标

在管线中增加 LLM 驱动的事实提取，将一段对话/文本分解为多条结构化事实。改动封装在 Chunker 内部，管线其余阶段（embed、index、relationship、profile、search）无需修改。

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
        # 3. 解析 JSON 响应
        # 4. 验证每条 Fact 字段
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
7. summary 字段为 1 句话简短摘要，用于搜索/画像展示

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
                            memory_type=f.memory_type,
                            confidence=f.confidence,
                            summary=f.summary,
                            metadata=metadata,
                        )
                        for f in facts
                    ]
            except Exception:
                logger.warning("fact_extraction_failed, falling back to turn chunking")

        # Phase 2: 回退 — 按轮次切割
        return self._chunk_by_turns(text, metadata)
```

**新增 SemanticTextChunker：**

```python
class SemanticTextChunker(BaseChunker):
    """text 类型的 LLM 事实提取分块器"""
    def __init__(self, fact_extractor: FactExtractor | None = None):
        self.fact_extractor = fact_extractor

    async def chunk(self, text, content_type, metadata=None) -> list[Chunk]:
        if self.fact_extractor:
            try:
                facts = await self.fact_extractor.extract(text, entity_context=...)
                if facts:
                    return [Chunk(text=f.text, memory_type=..., confidence=..., summary=...) for f in facts]
            except Exception:
                logger.warning("fact_extraction_failed, falling back to paragraph chunking")

        # 回退到 TextChunker 的段落分块
        return self._paragraph_chunking(text)
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

Chunker.chunk() 当前是同步方法。由于 LLM 调用是异步的，需要将 chunk 方法改为异步：

```python
# 改动前
class BaseChunker:
    def chunk(self, text, content_type, metadata=None) -> list[Chunk]:
        ...

# 改动后
class BaseChunker:
    async def chunk(self, text, content_type, metadata=None) -> list[Chunk]:
        ...
```

影响范围：
- `ChunkerRegistry.chunk()` → async
- `MemoryEngine._chunk()` → 已 await（因为调用 embedder 前有 await），改为 await chunk
- 所有 Chunker 子类 → chunk 方法加 async

### 3.9 文件结构

```
emerald/pipeline/chunking/
├── __init__.py
├── base.py            # BaseChunker — chunk() → async
├── registry.py        # ChunkerRegistry — chunk() → async
├── fact_extractor.py  # 新增：FactExtractor + DeepSeekFactExtractor
├── conversation.py    # 改动：注入 FactExtractor
├── text.py            # 改动：新增 SemanticTextChunker，或直接改 TextChunker
├── code.py            # 不变：chunk() → async（方法签名变更）
├── markdown.py        # 不变：chunk() → async
├── pdf.py             # 不变：chunk() → async
```

## 4. 下游影响分析

| 管线阶段 | 改动 |
|---|---|
| Extract | ❌ 不变 |
| Chunk | ✅ 新增 FactExtractor，ConversationChunker/TextChunker 注入 |
| Embed | ❌ 不变。输入仍为 list[Chunk] |
| Index (Graph) | ❌ 不变。memory_type 和 confidence 来自 Fact 而非硬编码 |
| Index (Vector) | ❌ 不变 |
| Relationship | ❌ 不变。细粒度事实上推断质量更高 |
| Profile | ❌ 不变。能真正区分 fact/preference/episodic |
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
    └── JSON 解析失败 → 回退
```

**每次降级都记录结构化日志**（fact_extraction_failed, reason=...），且不阻塞管线。

## 6. 测试策略

### 单元测试
- `DeepSeekFactExtractor.extract()` — mock httpx，测试 JSON 解析、字段验证、空响应
- `SemanticTextChunker.chunk()` — mock FactExtractor，测试事实→Chunk 转换
- `ConversationChunker.chunk()` — mock FactExtractor，测试降级回退
- `ChunkerRegistry.chunk()` — 验证正确的 chunker 被调用

### 集成测试
- 端到端：add conversation → 验证图谱中有多条记忆节点，有不同的 memory_type
- 降级测试：API key 为空时整个管线仍正常工作

### 负向测试
- LLM 返回非法 JSON → 回退无崩溃
- LLM 超时 → 回退无崩溃
- LLM 返回空 facts → 回退无崩溃

## 7. 不在此 scope 的内容

- 图谱搜索的关系扩展（下一个 P0）
- 关系推断升级为语义理解（P1）
- 首选项强化（P1）
- TypeScript SDK
- 框架集成
- 基准测试

## 8. 风险

| 风险 | 缓解 |
|---|---|
| LLM 提取质量不稳定 | temperature=0.1 增加确定性；结构化 JSON 输出强制格式 |
| LLM 延迟增加管线时间 | 15s 超时 + 降级；DeepSeek V4-Flash 快于大多数模型 |
| API 成本 | DeepSeek V4-Flash 极便宜（$0.14/M input），1K 字对话约 $0.0001 |
| async 方法签名变更影响广 | Chunker 子类数量有限（5 个），全部改 `def→async def` |
