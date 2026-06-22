# LLM Fact Extraction Implementation Plan

> **Review status:** v1.1 — passed plan review (2 blockers fixed: SYSTEM_PROMPT braces, _parse_code_fence)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add LLM-driven fact extraction (DeepSeek V4-Flash) to the conversation/text chunker, decomposing raw text into structured facts with proper memory_type/confidence/summary metadata.

**Architecture:** New `FactExtractor` (DeepSeek-backed) injected into `ConversationChunker` and new `SemanticTextChunker` (inherits `TextChunker`). Chunk dataclass extended with `memory_type`/`confidence`/`summary` fields. `chunk()` methods become async. Both sync (engine.py) and async (tasks.py) index paths read fields from Chunk instead of hardcoding. Fallback: LLM failure → original paragraph/turn chunking.

**Tech Stack:** Python 3.12, httpx, DeepSeek V4-Flash API (OpenAI-compatible), pytest-asyncio (already in dev deps)

**Spec:** `docs/superpowers/specs/2026-06-09-llm-fact-extraction-design.md`

---

### Task 1: Extend Chunk dataclass with fact metadata fields

**Files:**
- Modify: `emerald/pipeline/chunking/base.py` (Chunk dataclass, lines ~11-22)

- [ ] **Step 1: Add memory_type, confidence, summary fields to Chunk**

```python
@dataclass
class Chunk:
    text: str
    index: int
    token_count: int = 0
    content_type: str = "text"
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    # New: LLM fact extraction metadata
    memory_type: str = "fact"        # "fact" | "preference" | "episodic"
    confidence: float = 0.8          # 0.0 - 1.0
    summary: str = ""                # Brief summary for search/profile
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -c "from emerald.pipeline.chunking.base import Chunk; c = Chunk(text='test', index=0); assert c.memory_type == 'fact'; assert c.confidence == 0.8; assert c.summary == ''; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/base.py
git commit -m "feat(chunk): extend Chunk dataclass with memory_type, confidence, summary fields"
```

---

### Task 2: Change BaseChunker.chunk() to async

**Files:**
- Modify: `emerald/pipeline/chunking/base.py` (BaseChunker class, ~line 33)

- [ ] **Step 1: Change abstract method signature**

```python
# Before
@abstractmethod
def chunk(self, text: str, **kwargs) -> list[Chunk]:

# After
@abstractmethod
async def chunk(self, text: str, **kwargs) -> list[Chunk]:
```

- [ ] **Step 2: Verify import**

Run: `python -c "from emerald.pipeline.chunking.base import BaseChunker; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/base.py
git commit -m "feat(chunk): make BaseChunker.chunk() async"
```

---

### Task 3: Update ChunkerRegistry for async

**Files:**
- Modify: `emerald/pipeline/chunking/registry.py` (lines ~33-40)

- [ ] **Step 1: Change chunk() and run() to async**

```python
# Before
def run(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
    return self.chunk(text, content_type, **kwargs)

def chunk(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
    chunker = self.get(content_type)
    chunks = chunker.chunk(text, **kwargs)
    return chunks

# After
async def run(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
    return await self.chunk(text, content_type, **kwargs)

async def chunk(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
    chunker = self.get(content_type)
    chunks = await chunker.chunk(text, **kwargs)
    return chunks
```

- [ ] **Step 2: Verify**

Run: `python -c "from emerald.pipeline.chunking.registry import ChunkerRegistry; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/registry.py
git commit -m "feat(chunk): make ChunkerRegistry chunk() and run() async"
```

---

### Task 4: Convert all existing chunkers to async def

**Files:**
- Modify: `emerald/pipeline/chunking/text.py` (line ~30)
- Modify: `emerald/pipeline/chunking/conversation.py` (line ~31)
- Modify: `emerald/pipeline/chunking/code.py` (line ~70)
- Modify: `emerald/pipeline/chunking/markdown.py` (chunk method)
- Modify: `emerald/pipeline/chunking/pdf.py` (chunk method)

- [ ] **Step 1: Convert text.py — TextChunker.chunk()**

Change `def chunk(self, text: str, **kwargs) -> list[Chunk]:` to `async def chunk(self, text: str, **kwargs) -> list[Chunk]:`

- [ ] **Step 2: Convert conversation.py — ConversationChunker.chunk()**

Change `def chunk(self, text: str, **kwargs) -> list[Chunk]:` to `async def chunk(self, text: str, **kwargs) -> list[Chunk]:`

- [ ] **Step 3: Convert code.py — CodeChunker.chunk()**

Change `def chunk(self, text: str, **kwargs) -> list[Chunk]:` to `async def chunk(self, text: str, **kwargs) -> list[Chunk]:`

- [ ] **Step 4: Convert markdown.py and pdf.py**

Same mechanical change on their `chunk()` lines.

- [ ] **Step 5: Verify all chunkers import cleanly**

Run: `python -c "from emerald.pipeline.chunking.text import TextChunker; from emerald.pipeline.chunking.conversation import ConversationChunker; from emerald.pipeline.chunking.code import CodeChunker; from emerald.pipeline.chunking.markdown import MarkdownChunker; from emerald.pipeline.chunking.pdf import PDFChunker; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add emerald/pipeline/chunking/text.py emerald/pipeline/chunking/conversation.py emerald/pipeline/chunking/code.py emerald/pipeline/chunking/markdown.py emerald/pipeline/chunking/pdf.py
git commit -m "feat(chunk): convert all chunker chunk() methods to async def"
```

---

### Task 5: Create FactExtractor + DeepSeekFactExtractor

**Files:**
- Create: `emerald/pipeline/chunking/fact_extractor.py`

- [ ] **Step 1: Write fact_extractor.py**

```python
"""LLM-driven fact extraction from text/conversation content.

Extracts structured facts (type, confidence, summary) using DeepSeek V4-Flash.
Falls back gracefully on any API failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from emerald.config import get_settings

logger = structlog.get_logger(__name__)

# Template prompt — format with max_facts before sending.
# NOTE: the braces {{ and }} are literal JSON braces; .format() handles them.
_SYSTEM_PROMPT_TEMPLATE = """你是事实提取引擎。从对话/文本中提取细粒度、独立的事实。
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
6. 最多 {max_facts} 条。无事实时返回空数组
7. summary 字段为 1 句话简短摘要（与原文保持相同语言），用于搜索/画像展示

输出严格 JSON：
{{"facts": [{{"text": "...", "type": "fact|preference|episodic", "confidence": 0.85, "summary": "..."}}]}}"""


@dataclass
class Fact:
    text: str
    memory_type: str      # "fact" | "preference" | "episodic"
    confidence: float     # 0.0 - 1.0
    summary: str          # Brief summary


class FactExtractor:
    """Abstract base for LLM-driven fact extraction."""

    async def extract(self, text: str, *, entity_context: str | None = None) -> list[Fact]:
        raise NotImplementedError


class DeepSeekFactExtractor(FactExtractor):
    """Fact extraction via DeepSeek V4-Flash (OpenAI-compatible API)."""

    VALID_TYPES = frozenset({"fact", "preference", "episodic"})

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        max_facts: int = 20,
        timeout: float = 15.0,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_facts = max_facts
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def extract(self, text: str, *, entity_context: str | None = None) -> list[Fact]:
        if not text.strip():
            return []

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(max_facts=self._max_facts)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        user_content = text
        if entity_context:
            user_content = f"上下文提示：{entity_context}\n\n文本：{text}"
        messages.append({"role": "user", "content": user_content})

        raw_content: str | None = None
        raw = await self._call_api(messages, raw_content_ref=[raw_content])
        if raw is None:
            return []

        return self._parse_and_validate(raw)

    async def _call_api(
        self, messages: list[dict[str, str]], raw_content_ref: list[str | None]
    ) -> dict[str, Any] | None:
        """Call DeepSeek API. Returns parsed JSON dict, or None on failure.

        First attempts response_format: json_object. On JSON parse failure,
        strips markdown code fences from the raw content string and re-parses.
        """
        raw_content: str = ""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "temperature": self._temperature,
                        "max_tokens": self._max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_content = data["choices"][0]["message"]["content"]
                raw_content_ref[0] = raw_content
                return json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning("fact_extraction.json_parse_failed, trying code fences")
            return self._strip_code_fences(raw_content)
        except KeyError as e:
            logger.warning("fact_extraction.unexpected_api_response", error=str(e))
            return None
        except Exception:
            logger.warning("fact_extraction.api_failed", exc_info=True)
            return None

    @staticmethod
    def _strip_code_fences(raw_content: str) -> dict[str, Any] | None:
        """Strip markdown code fences from raw LLM output, then parse as JSON."""
        stripped = re.sub(r"^```(?:json)?\s*", "", raw_content.strip())
        stripped = re.sub(r"\s*```$", "", stripped)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    def _parse_and_validate(self, raw: dict[str, Any]) -> list[Fact]:
        """Parse LLM output, validate each fact, return clean list."""
        raw_facts = raw.get("facts", [])
        if not isinstance(raw_facts, list):
            return []

        facts: list[Fact] = []
        seen_texts: set[str] = set()

        for item in raw_facts:
            if not isinstance(item, dict):
                continue

            text = str(item.get("text", "")).strip()
            if not text:
                logger.warning("fact_extraction.empty_text_skipped")
                continue

            # Dedup
            normalized = re.sub(r"\s+", "", text)
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            # Validate type
            memory_type = str(item.get("type", "fact")).lower()
            if memory_type not in self.VALID_TYPES:
                logger.warning("fact_extraction.invalid_type", type=memory_type)
                memory_type = "fact"

            # Validate confidence
            confidence = float(item.get("confidence", 0.8))
            confidence = max(0.0, min(1.0, confidence))

            summary = str(item.get("summary", ""))[:200]

            facts.append(Fact(
                text=text,
                memory_type=memory_type,
                confidence=confidence,
                summary=summary,
            ))

            if len(facts) >= self._max_facts:
                break

        return facts


def get_fact_extractor() -> FactExtractor | None:
    """Create a DeepSeekFactExtractor if API key is configured, else None."""
    settings = get_settings()
    if not settings.deepseek_api_key:
        logger.info("fact_extraction.disabled", reason="no_api_key")
        return None
    return DeepSeekFactExtractor(
        api_key=settings.deepseek_api_key,
        model=settings.fact_extraction_model,
        base_url=settings.fact_extraction_base_url,
        max_facts=settings.fact_extraction_max_facts,
        timeout=settings.fact_extraction_timeout,
        temperature=settings.fact_extraction_temperature,
        max_tokens=settings.fact_extraction_max_tokens,
    )
```

- [ ] **Step 2: Verify module imports**

Run: `python -c "from emerald.pipeline.chunking.fact_extractor import FactExtractor, DeepSeekFactExtractor, Fact; f = Fact(text='test', memory_type='fact', confidence=0.9, summary='s'); print(f)"`

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/fact_extractor.py
git commit -m "feat(chunk): add FactExtractor + DeepSeekFactExtractor"
```

---

### Task 6: Add DeepSeek config fields

**Files:**
- Modify: `emerald/config.py` — inside Settings class, before closing brace and `@lru_cache`

- [ ] **Step 1: Add DeepSeek + fact extraction settings**

Insert inside the `Settings` class (before the closing lines with `@lru_cache`):

```python
    # ---- DeepSeek / Fact Extraction ----
    deepseek_api_key: str = ""

    fact_extraction_model: str = "deepseek-v4-flash"
    fact_extraction_base_url: str = "https://api.deepseek.com"
    fact_extraction_max_facts: int = 20
    fact_extraction_timeout: float = 15.0
    fact_extraction_temperature: float = 0.1
    fact_extraction_max_tokens: int = 2000
```

- [ ] **Step 2: Verify**

Run: `python -c "from emerald.config import get_settings; s = get_settings(); print(s.deepseek_api_key, s.fact_extraction_model)"`

- [ ] **Step 3: Commit**

```bash
git add emerald/config.py
git commit -m "feat(config): add DeepSeek and fact extraction settings"
```

---

### Task 7: Wire FactExtractor into ConversationChunker

**Files:**
- Modify: `emerald/pipeline/chunking/conversation.py`

- [ ] **Step 0: Add imports** at the top of conversation.py:

```python
import structlog
from emerald.pipeline.chunking.fact_extractor import FactExtractor

logger = structlog.get_logger(__name__)
```

- [ ] **Step 1: Add constructor to ConversationChunker**

```python
class ConversationChunker(BaseChunker):
    target_size = 512
    overlap_size = 0
    _chars_per_token = 4

    def __init__(self, fact_extractor: FactExtractor | None = None):
        self.fact_extractor = fact_extractor

    async def chunk(self, text: str, **kwargs) -> list[Chunk]:
        if not text.strip():
            return []

        # Phase 1: LLM fact extraction
        if self.fact_extractor:
            try:
                metadata = kwargs.get("metadata") or {}
                entity_context = metadata.get("entity_context")
                facts = await self.fact_extractor.extract(
                    text, entity_context=entity_context
                )
                if facts:
                    return [
                        Chunk(
                            text=f.text,
                            index=i,
                            content_type="conversation",
                            memory_type=f.memory_type,
                            confidence=f.confidence,
                            summary=f.summary,
                            metadata={"speaker": "unknown", "turn_index": i},
                        )
                        for i, f in enumerate(facts)
                    ]
            except Exception:
                logger.warning(
                    "fact_extraction_failed",
                    content_type="conversation",
                    exc_info=True,
                )

        # Phase 2: Fallback — existing turn-based chunking (unchanged)
        # ... (existing _split_turns + _chunk_by_size logic remains as-is)
```

Note: The fallback code (existing `_split_turns` + `_chunk_by_size`) remains completely unchanged. Just prepend the LLM extraction phase above it.

- [ ] **Step 2: Verify existing chunker tests pass (after async migration)**

Run: `pytest tests/pipeline/test_conversation_chunker.py -v` (will fail until Task 12 migration, expected)

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/conversation.py
git commit -m "feat(chunk): wire FactExtractor into ConversationChunker"
```

---

### Task 8: Create SemanticTextChunker (extends TextChunker)

**Files:**
- Modify: `emerald/pipeline/chunking/text.py` — add class at end of file

- [ ] **Step 0: Add imports** at the top of text.py:

```python
from emerald.pipeline.chunking.fact_extractor import FactExtractor
import structlog

logger = structlog.get_logger(__name__)
```

- [ ] **Step 1: Add SemanticTextChunker class at end of text.py**

```python
class SemanticTextChunker(TextChunker):
    """Text chunker with LLM fact extraction. Inherits TextChunker for fallback."""

    def __init__(self, fact_extractor: FactExtractor | None = None, **kwargs):
        super().__init__(**kwargs)
        self.fact_extractor = fact_extractor

    async def chunk(self, text: str, **kwargs) -> list[Chunk]:
        if not text.strip():
            return []

        # Phase 1: LLM fact extraction
        if self.fact_extractor:
            try:
                metadata = kwargs.get("metadata") or {}
                entity_context = metadata.get("entity_context")
                facts = await self.fact_extractor.extract(
                    text, entity_context=entity_context
                )
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
                logger.warning(
                    "fact_extraction_failed",
                    content_type="text",
                    exc_info=True,
                )

        # Phase 2: Fallback — parent's paragraph/sentence chunking
        return await super().chunk(text, **kwargs)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from emerald.pipeline.chunking.text import SemanticTextChunker, TextChunker; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add emerald/pipeline/chunking/text.py
git commit -m "feat(chunk): add SemanticTextChunker with LLM fact extraction"
```

---

### Task 9: Update app.py to inject FactExtractor into chunkers

**Files:**
- Modify: `emerald/api/app.py` — `_init_engine()` function

- [ ] **Step 1: Build FactExtractor and inject into chunkers**

In `_init_engine()`, change the chunker registration section. Replace:
```python
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", ConversationChunker())
    chunkers.register("markdown", MarkdownChunker())
```

With:
```python
    from emerald.pipeline.chunking.fact_extractor import get_fact_extractor
    from emerald.pipeline.chunking.text import SemanticTextChunker

    fact_extractor = get_fact_extractor()

    chunkers = ChunkerRegistry()
    chunkers.register("text", SemanticTextChunker(fact_extractor=fact_extractor))
    chunkers.register("conversation", ConversationChunker(fact_extractor=fact_extractor))
    chunkers.register("markdown", MarkdownChunker())
```

The PDF and Code chunker registrations (in try/except blocks) remain unchanged.

- [ ] **Step 2: Verify app imports**

Run: `python -c "from emerald.api.app import _init_engine; engine = _init_engine(); print(type(engine).__name__)"`

- [ ] **Step 3: Commit**

```bash
git add emerald/api/app.py
git commit -m "feat(app): inject FactExtractor into ConversationChunker and SemanticTextChunker"
```

---

### Task 10: Update engine.py sync index path to read chunk fields

**Files:**
- Modify: `emerald/core/engine.py` — `_chunk()` call (~line 105), `_chunk()` def (~line 186), `_index()` call (~line 264-268), metric (~line 130)

- [ ] **Step 1: Await _chunk() call**

At ~line 105:
```python
# Before
chunks = self._chunk(extracted, content_type)

# After
chunks = await self._chunk(extracted, content_type)
```

- [ ] **Step 2: Make _chunk() async**

At ~line 186:
```python
# Before
def _chunk(self, extracted, content_type) -> list[Chunk]:
    return self.chunkers.chunk(extracted.text, content_type, metadata=extracted.metadata)

# After
async def _chunk(self, extracted, content_type) -> list[Chunk]:
    return await self.chunkers.chunk(extracted.text, content_type, metadata=extracted.metadata)
```

- [ ] **Step 3: Read memory_type/confidence/summary from chunk in _index()**

At ~line 264-268:
```python
# Before
memory_id = await self.graph.create_memory(
    content=chunk.text,
    entity_id=entity_id,
    memory_type="fact",
    confidence=0.8,
    source_type="conversation" if content_type == "conversation" else "document",
    metadata=metadata,
)

# After
memory_id = await self.graph.create_memory(
    content=chunk.text,
    entity_id=entity_id,
    memory_type=chunk.memory_type,
    confidence=chunk.confidence,
    summary=chunk.summary or None,
    source_type="conversation" if content_type == "conversation" else "document",
    metadata=metadata,
)
```

- [ ] **Step 4: Fix metric label to count by actual memory_type**

At ~line 130:
```python
# Before
memory_add_total.labels(memory_type="fact").inc(len(memory_ids))

# After
from collections import Counter
type_counts = Counter(chunk.memory_type for chunk in chunks)
for mt, count in type_counts.items():
    memory_add_total.labels(memory_type=mt).inc(count)
```

- [ ] **Step 5: Verify existing engine tests**

Run: `pytest tests/core/test_memory_engine.py -v` (may fail until test migration, expected)

- [ ] **Step 6: Commit**

```bash
git add emerald/core/engine.py
git commit -m "feat(engine): read memory_type/confidence/summary from Chunk; fix metric labels"
```

---

### Task 11: Update tasks.py async pipeline

**Files:**
- Modify: `emerald/pipeline/tasks.py` — chunk call (~line 93), chunk serialization (~lines 95-98), index create_memory (~lines 176-180)

- [ ] **Step 1: Await chunker.chunk() call**

At ~line 93:
```python
# Before
chunks = chunker.chunk(text or "")

# After
chunks = await chunker.chunk(text or "")
```

- [ ] **Step 2: Add new fields to chunk serialization**

At ~lines 95-98:
```python
# Before
data = [
    {"id": c.id, "text": c.text, "index": c.index, "token_count": c.token_count}
    for c in chunks
]

# After
data = [
    {
        "id": c.id, "text": c.text, "index": c.index,
        "token_count": c.token_count,
        "memory_type": c.memory_type,
        "confidence": c.confidence,
        "summary": c.summary,
    }
    for c in chunks
]
```

- [ ] **Step 3: Read fields in _run_index()**

At ~lines 176-180:
```python
# Before
mid = await graph.create_memory(
    content=chunk_data["text"],
    entity_id=entity_id,
    memory_type="fact",
    confidence=0.8,
    source_type="document",
)

# After
mid = await graph.create_memory(
    content=chunk_data["text"],
    entity_id=entity_id,
    memory_type=chunk_data.get("memory_type", "fact"),
    confidence=chunk_data.get("confidence", 0.8),
    summary=chunk_data.get("summary") or None,  # empty string → None
    source_type="document",
)
```

- [ ] **Step 4: Verify Celery pipeline integration test**

Run: `pytest tests/integration/test_celery_pipeline.py -v` (may need Docker)

- [ ] **Step 5: Commit**

```bash
git add emerald/pipeline/tasks.py
git commit -m "feat(tasks): async chunk call, serialize new fields, read in index stage"
```

---

### Task 12: Migrate all chunker tests to async

**Files (53 call sites across 8 files):**
- Modify: `tests/unit/test_chunker_registry.py` (1 call)
- Modify: `tests/pipeline/test_conversation_chunker.py` (6 calls)
- Modify: `tests/pipeline/test_text_chunker.py` (7 calls)
- Modify: `tests/pipeline/test_markdown_chunker.py` (5 calls)
- Modify: `tests/pipeline/test_code_chunker.py` (12 calls)
- Modify: `tests/pipeline/test_pdf_chunker.py` (4 calls)
- Modify: `tests/pipeline/test_default_registry.py` (1 call)
- Modify: `tests/unit/test_conversation_chunking_markdown_bold.py` (17 calls)

- [ ] **Step 1-8: For each file, change `def test_` → `async def test_` and `chunker.chunk(` → `await chunker.chunk(`**

Mechanical change: every `.chunk(...)` call gets `await` prepended, every test function gets `async`. Files are already using `pytest-asyncio` (configured in pyproject.toml with `asyncio_mode = "auto"`).

- [ ] **Step 9: Run all chunker tests to verify**

Run: `pytest tests/pipeline/ tests/unit/test_chunker_registry.py tests/unit/test_conversation_chunking_markdown_bold.py -v`

Expected: all pass (no async-related failures).

- [ ] **Step 10: Commit**

```bash
git add tests/
git commit -m "test: migrate all chunker tests to async def + await"
```

---

### Task 13: Write FactExtractor unit tests

**Files:**
- Create: `tests/pipeline/test_fact_extractor.py`

- [ ] **Step 1: Write test file covering all validation rules**

Tests for:
- Valid JSON response → facts extracted correctly
- Empty text → returns []
- API failure → returns []
- Invalid memory_type → coerced to "fact"
- Confidence out of range → clamped
- Empty text in fact → skipped
- Duplicate facts → deduped
- Max facts cap → truncated

(Refer to the plan v1.0 for the full test code in Git history, or write fresh using the Fact dataclass.)

- [ ] **Step 2: Run tests**

Run: `pytest tests/pipeline/test_fact_extractor.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/pipeline/test_fact_extractor.py
git commit -m "test: add DeepSeekFactExtractor unit tests"
```

---

### Task 14: Write SemanticTextChunker tests

**Files:**
- Create: `tests/pipeline/test_semantic_text_chunker.py`

- [ ] **Step 1: Write tests for LLM path and fallback**

Tests for:
- With mock FactExtractor → facts converted to Chunks with correct fields
- With FactExtractor returning [] → falls back to parent TextChunker
- Without FactExtractor → directly delegates to parent
- FactExtractor raises exception → falls back gracefully

- [ ] **Step 2: Run tests**

Run: `pytest tests/pipeline/test_semantic_text_chunker.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/pipeline/test_semantic_text_chunker.py
git commit -m "test: add SemanticTextChunker tests"
```

---

### Task 15: Full test suite verification

- [ ] **Step 1: Run complete test suite**

Run: `pytest -v`

Expected: all previously passing tests still pass, plus new tests pass. Any regressions are likely async-related test migration misses.

- [ ] **Step 2: Fix any remaining test failures**

- [ ] **Step 3: Run with coverage**

Run: `pytest --cov=emerald/pipeline/chunking/fact_extractor --cov=emerald/pipeline/chunking/text --cov-report=term-missing`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: fix remaining async migration issues; full test suite green"
```
